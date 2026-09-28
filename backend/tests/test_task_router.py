"""Tests for multi-LLM task router and provider manager."""

from unittest.mock import patch, MagicMock
import pytest
import time

from lib.provider_manager import (
    ProviderManager,
    Provider,
    ProviderStatus,
    TaskType,
    classify_task,
    TASK_ROUTING,
    get_manager,
    generate_text,
    generate_chat,
    PER_PROVIDER_TIMEOUT,
    GLOBAL_TIMEOUT,
)


class TestClassifyTask:
    """Tests for the task classifier (heuristic, no LLM call)."""

    def test_short_message_is_quick_chat(self):
        assert classify_task("hello") == TaskType.QUICK_CHAT
        assert classify_task("thanks") == TaskType.QUICK_CHAT
        assert classify_task("what is that") == TaskType.QUICK_CHAT

    def test_calculation_keywords(self):
        assert classify_task("calculate the margin") == TaskType.CALCULATION
        assert classify_task("what is the ROE formula") == TaskType.CALCULATION
        assert classify_task("how was FCF calculated") == TaskType.CALCULATION
        assert classify_task("step by step derivation of revenue") == TaskType.CALCULATION

    def test_heavy_reasoning_keywords(self):
        assert classify_task("compare this company with its peers") == TaskType.HEAVY_REASONING
        assert classify_task("evaluate the investment opportunity") == TaskType.HEAVY_REASONING
        assert classify_task("should I invest in this company") == TaskType.HEAVY_REASONING
        assert classify_task("what are the pros and cons") == TaskType.HEAVY_REASONING
        assert classify_task("deep dive into DCF valuation") == TaskType.HEAVY_REASONING

    def test_research_with_context(self):
        assert classify_task("what does this company do", has_research_context=True) == TaskType.RESEARCH
        assert classify_task("tell me about the revenue", has_research_context=True) == TaskType.RESEARCH

    def test_research_without_context_falls_back(self):
        assert classify_task("tell me about something random", has_research_context=False) == TaskType.QUICK_CHAT

    def test_financial_keywords_with_context(self):
        assert classify_task("what is the revenue", has_research_context=True) == TaskType.RESEARCH
        assert classify_task("describe the business model", has_research_context=True) == TaskType.RESEARCH


class TestProviderRegistration:
    """Tests for provider registration based on env vars."""

    def test_providers_registered(self):
        mgr = ProviderManager()
        # Should have 3 providers (NVIDIA + two OpenRouter fallbacks)
        assert len(mgr._providers) == 3

    def test_provider_names(self):
        mgr = ProviderManager()
        names = set(mgr._providers.keys())
        assert "nvidia_nemotron" in names
        assert "openrouter_nemotron" in names
        assert "openrouter_nemotron_ultra" in names
        # Deprecated/broken providers are removed
        assert "nvidia_nemotron_lightning" not in names
        assert "openrouter_minimax_m3" not in names

    def test_providers_have_correct_models(self):
        mgr = ProviderManager()
        assert mgr._providers["nvidia_nemotron"].model == "nvidia/nemotron-3-super-120b-a12b"
        assert mgr._providers["openrouter_nemotron"].model == "nvidia/nemotron-3-super-120b-a12b:free"
        assert mgr._providers["openrouter_nemotron_ultra"].model == "nvidia/nemotron-3-ultra-550b-a55b:free"

    def test_nvidia_providers_use_nvidia_base_url(self):
        mgr = ProviderManager()
        nvidia_base = "https://integrate.api.nvidia.com/v1"
        assert mgr._providers["nvidia_nemotron"].base_url == nvidia_base

    def test_openrouter_providers_use_openrouter_base_url(self):
        mgr = ProviderManager()
        openrouter_base = "https://openrouter.ai/api/v1"
        assert mgr._providers["openrouter_nemotron"].base_url == openrouter_base
        assert mgr._providers["openrouter_nemotron_ultra"].base_url == openrouter_base


class TestTaskRouting:
    """Tests for the task routing table."""

    def test_all_task_types_have_routing(self):
        for task_type in TaskType:
            assert task_type in TASK_ROUTING, f"Missing routing for {task_type}"

    def test_routing_has_required_fields(self):
        for task_type, routing in TASK_ROUTING.items():
            for entry in routing:
                assert "provider" in entry, f"Missing 'provider' in {task_type}"
                assert "max_tokens" in entry, f"Missing 'max_tokens' in {task_type}"

    def test_quick_chat_prefers_reliable_providers(self):
        quick_routing = TASK_ROUTING[TaskType.QUICK_CHAT]
        # NVIDIA Nemotron (NIM) should be first (reliable ~3s, primary provider)
        assert quick_routing[0]["provider"] == "nvidia_nemotron"
        assert quick_routing[0]["max_tokens"] <= 512

    def test_heavy_reasoning_prefers_powerful_providers(self):
        heavy_routing = TASK_ROUTING[TaskType.HEAVY_REASONING]
        # Nemotron Ultra should be first (most powerful)
        assert heavy_routing[0]["provider"] == "openrouter_nemotron_ultra"
        assert heavy_routing[0]["max_tokens"] >= 1024

    def test_calculation_uses_low_temperature(self):
        calc_routing = TASK_ROUTING[TaskType.CALCULATION]
        assert calc_routing[0]["temperature"] <= 0.2

    def test_intent_classify_uses_minimal_tokens(self):
        intent_routing = TASK_ROUTING[TaskType.INTENT_CLASSIFY]
        assert intent_routing[0]["max_tokens"] <= 128


class TestProviderHealth:
    """Tests for provider health tracking."""

    def test_provider_starts_healthy(self):
        p = Provider(name="test", model="test", base_url="http://test.com", api_key_env="TEST")
        assert p.is_available() is True
        assert p.status == ProviderStatus.HEALTHY

    def test_rate_limiting(self):
        p = Provider(name="test", model="test", base_url="http://test.com", api_key_env="TEST")
        p.mark_rate_limited(60.0)
        assert p.is_available() is False
        assert p.status == ProviderStatus.RATE_LIMITED

    def test_error_with_short_cooldown(self):
        p = Provider(name="test", model="test", base_url="http://test.com", api_key_env="TEST")
        p.mark_error(0.01)
        assert p.is_available() is False
        time.sleep(0.02)
        assert p.is_available() is True

    def test_auth_failed_long_cooldown(self):
        p = Provider(name="test", model="test", base_url="http://test.com", api_key_env="TEST")
        p.mark_auth_failed()
        assert p.is_available() is False
        assert p.get_cooldown_remaining() > 80000

    def test_unconfigured_always_unavailable(self):
        p = Provider(
            name="test", model="test", base_url="http://test.com",
            api_key_env="TEST", status=ProviderStatus.UNCONFIGURED,
        )
        assert p.is_available() is False

    def test_mark_healthy_clears_cooldown(self):
        p = Provider(name="test", model="test", base_url="http://test.com", api_key_env="TEST")
        p.mark_error(60.0)
        assert p.is_available() is False
        p.mark_healthy()
        assert p.is_available() is True
        assert p.error_count == 0

    def test_mark_healthy_updates_avg_latency(self):
        p = Provider(name="test", model="test", base_url="http://test.com", api_key_env="TEST")
        p.total_requests = 5
        p.mark_healthy(2.0)
        # Running average: ((0.0 * 4) + 2.0) / 5 = 0.4
        assert p.avg_latency == 0.4


class TestSelectProvidersForTask:
    """Tests for provider selection per task type."""

    def test_select_returns_available_providers(self):
        mgr = ProviderManager()
        mgr._providers["nvidia_nemotron"].mark_rate_limited()
        candidates = mgr._select_providers_for_task(TaskType.QUICK_CHAT)
        provider_names = [c[0].name for c in candidates]
        assert "nvidia_nemotron" not in provider_names
        assert len(candidates) >= 1

    def test_select_falls_back_when_primary_down(self):
        mgr = ProviderManager()
        mgr._providers["nvidia_nemotron"].mark_rate_limited()
        candidates = mgr._select_providers_for_task(TaskType.QUICK_CHAT)
        assert len(candidates) >= 1


class TestTimeouts:
    """Tests for timeout configuration."""

    def test_per_provider_timeout_is_reasonable(self):
        assert PER_PROVIDER_TIMEOUT == 15.0

    def test_global_timeout_is_reasonable(self):
        assert GLOBAL_TIMEOUT == 30.0

    def test_global_timeout_greater_than_per_provider(self):
        assert GLOBAL_TIMEOUT > PER_PROVIDER_TIMEOUT


class TestProviderStatus:
    """Tests for the status endpoint."""

    def test_status_structure(self):
        mgr = ProviderManager()
        status = mgr.get_status()
        assert "providers" in status
        assert "strategy" in status
        assert status["strategy"] == "fast_failover"
        assert "total_providers" in status
        assert status["total_providers"] == 3

    def test_status_includes_timeout_info(self):
        mgr = ProviderManager()
        status = mgr.get_status()
        assert status["per_provider_timeout"] == PER_PROVIDER_TIMEOUT
        assert status["global_timeout"] == GLOBAL_TIMEOUT

    def test_status_includes_tags(self):
        mgr = ProviderManager()
        status = mgr.get_status()
        for p in status["providers"]:
            assert "tags" in p


class TestSingletonManager:
    def test_singleton_returns_same_instance(self):
        mgr1 = get_manager()
        mgr2 = get_manager()
        assert mgr1 is mgr2
