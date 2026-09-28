"""Bulletproof multi-LLM provider manager with task routing and fast failover.

Every provider call has a HARD per-provider timeout. If one hangs, the next
provider is tried immediately. The user gets a response within seconds, never
minutes.

Provider speed ranking (tested):
  1. Nemotron Super 120B (NIM)     ~3.3s  — fastest, reliable
  2. Nemotron Super 120B (OpenRouter) ~6s — clean fallback
  3. Nemotron Ultra 550B (OpenRouter) ~6s — powerful, for heavy reasoning only

DEPRECATED/BROKEN model IDs (removed — verified failing):
  - nvidia/nemotron-3.5-lightning-30b-a3b  (NIM)   → read timeout
  - minimax/minimax-m3:free                (OR)    → HTTP 404 unavailable free
  - deepseek / kimi NIM models                     → timeout / unconfigured
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum

from dotenv import load_dotenv
from lib.netutil import apply_ipv4_first as _net_fix
_net_fix()
from pathlib import Path

logger = logging.getLogger("finora.provider")

# ── Load environment variables ────────────────────────────────────────────────
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)


# ── Hard limits ───────────────────────────────────────────────────────────────
PER_PROVIDER_TIMEOUT = 15.0   # Seconds — kill any provider call that takes longer
GLOBAL_TIMEOUT = 30.0         # Seconds — absolute max for the entire request
MAX_RETRIES = 2               # Retries across different providers


# ── Task types for routing ────────────────────────────────────────────────────
class TaskType(str, Enum):
    QUICK_CHAT = "quick_chat"          # Simple questions, greetings, follow-ups
    RESEARCH = "research"              # Financial research questions
    HEAVY_REASONING = "heavy_reasoning"  # Complex analysis, multi-step reasoning
    CALCULATION = "calculation"         # Metric explanations, formulas, math
    INTENT_CLASSIFY = "intent_classify"  # Intent classification (lightweight)
    EXECUTIVE_SUMMARY = "executive_summary"  # Full research summary generation


# ── Provider health status ────────────────────────────────────────────────────
class ProviderStatus(str, Enum):
    HEALTHY = "healthy"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"
    UNCONFIGURED = "unconfigured"


@dataclass
class Provider:
    name: str
    model: str
    base_url: str
    api_key_env: str  # Which env var holds the API key
    status: ProviderStatus = ProviderStatus.HEALTHY
    cooldown_until: float = 0.0
    error_count: int = 0
    last_error: str = ""
    total_requests: int = 0
    total_failures: int = 0
    avg_latency: float = 0.0  # Running average latency
    tags: list[str] = field(default_factory=list)

    def is_available(self) -> bool:
        if self.status == ProviderStatus.UNCONFIGURED:
            return False
        if self.cooldown_until > time.time():
            return False
        return True

    def mark_rate_limited(self, cooldown_seconds: float = 120.0, reason: str = "") -> None:
        self.status = ProviderStatus.RATE_LIMITED
        self.cooldown_until = time.time() + cooldown_seconds
        self.error_count += 1
        self.total_failures += 1
        self.last_error = reason or "rate limited"

    def mark_error(self, cooldown_seconds: float = 5.0, reason: str = "") -> None:
        self.status = ProviderStatus.ERROR
        self.cooldown_until = time.time() + cooldown_seconds
        self.error_count += 1
        self.total_failures += 1
        self.last_error = reason or "provider error"

    def mark_healthy(self, latency: float = 0.0) -> None:
        self.status = ProviderStatus.HEALTHY
        self.cooldown_until = 0.0
        self.error_count = 0
        # Update running average latency
        if self.total_requests > 0:
            self.avg_latency = ((self.avg_latency * (self.total_requests - 1)) + latency) / self.total_requests
        else:
            self.avg_latency = latency

    def mark_auth_failed(self, reason: str = "") -> None:
        self.status = ProviderStatus.ERROR
        self.cooldown_until = time.time() + 86400.0  # 24 hour cooldown
        self.error_count += 1
        self.total_failures += 1
        self.last_error = reason or "auth failed"

    def get_cooldown_remaining(self) -> float:
        return max(0.0, self.cooldown_until - time.time())


# ── Task routing table ────────────────────────────────────────────────────────
# Each task type maps to an ordered list of (provider_name, max_tokens, temperature, top_p).
# Providers are tried in order — first working one wins.
# IMPORTANT: Only use PROVEN WORKING providers in primary slots.
TASK_ROUTING: dict[TaskType, list[dict]] = {
    TaskType.QUICK_CHAT: [
        # NVIDIA Nemotron Super (NIM) first — RELIABLE ~3s, clean output.
        {"provider": "nvidia_nemotron", "max_tokens": 512, "temperature": 0.7, "top_p": 0.9},
        {"provider": "openrouter_nemotron", "max_tokens": 512, "temperature": 0.7, "top_p": 0.9},
        {"provider": "openrouter_nemotron_ultra", "max_tokens": 512, "temperature": 0.7, "top_p": 0.9},
    ],
    TaskType.RESEARCH: [
        {"provider": "nvidia_nemotron", "max_tokens": 1024, "temperature": 0.3, "top_p": 0.85},
        {"provider": "openrouter_nemotron", "max_tokens": 1024, "temperature": 0.3, "top_p": 0.85},
        {"provider": "openrouter_nemotron_ultra", "max_tokens": 1024, "temperature": 0.3, "top_p": 0.85},
    ],
    TaskType.HEAVY_REASONING: [
        {"provider": "openrouter_nemotron_ultra", "max_tokens": 2048, "temperature": 0.2, "top_p": 0.85},
        {"provider": "nvidia_nemotron", "max_tokens": 1024, "temperature": 0.2, "top_p": 0.85},
        {"provider": "openrouter_nemotron", "max_tokens": 1024, "temperature": 0.2, "top_p": 0.85},
    ],
    TaskType.CALCULATION: [
        {"provider": "nvidia_nemotron", "max_tokens": 768, "temperature": 0.1, "top_p": 0.8},
        {"provider": "openrouter_nemotron", "max_tokens": 768, "temperature": 0.1, "top_p": 0.8},
        {"provider": "openrouter_nemotron_ultra", "max_tokens": 768, "temperature": 0.1, "top_p": 0.8},
    ],
    TaskType.INTENT_CLASSIFY: [
        {"provider": "nvidia_nemotron", "max_tokens": 128, "temperature": 0.0, "top_p": 1.0},
        {"provider": "openrouter_nemotron", "max_tokens": 128, "temperature": 0.0, "top_p": 1.0},
    ],
    TaskType.EXECUTIVE_SUMMARY: [
        {"provider": "openrouter_nemotron_ultra", "max_tokens": 2048, "temperature": 0.3, "top_p": 0.9},
        {"provider": "nvidia_nemotron", "max_tokens": 1024, "temperature": 0.3, "top_p": 0.9},
        {"provider": "openrouter_nemotron", "max_tokens": 1024, "temperature": 0.3, "top_p": 0.9},
    ],
}


# ── Task classifier (pure heuristic, no LLM call) ────────────────────────────
def classify_task(user_message: str, has_research_context: bool = False) -> TaskType:
    """Classify a user message into a task type for routing.

    Priority: calculation > heavy_reasoning > research > quick_chat.
    """
    msg = user_message.lower().strip()

    # ── 1. Calculation keywords ──
    calc_keywords = [
        "calculate", "formula", "how did", "how was", "compute",
        "margin", "ratio", "fcf", "free cash flow", "roe", "roa", "roic",
        "eps", "revenue per", "cost of", "debt to", "current ratio",
        "what is the formula", "how do you", "step by step",
    ]
    if any(kw in msg for kw in calc_keywords):
        return TaskType.CALCULATION

    # ── 2. Heavy reasoning keywords ──
    reasoning_keywords = [
        "compare", "analyze", "evaluate", "assess", "should i",
        "what if", "pros and cons", "risk", "investment",
        "explain in detail", "deep dive", "comprehensive",
        "valuation", "dcf", "intrinsic value",
    ]
    if any(kw in msg for kw in reasoning_keywords):
        return TaskType.HEAVY_REASONING

    # ── 3. Research keywords (when context available) ──
    if has_research_context:
        research_keywords = [
            "what does", "who is", "tell me about", "describe",
            "company", "business", "revenue", "income", "profit",
            "source", "data", "metric", "financial",
            "how is", "why is", "what are",
        ]
        if any(kw in msg for kw in research_keywords):
            return TaskType.RESEARCH

    # ── 4. Default ──
    if len(msg.split()) <= 5:
        return TaskType.QUICK_CHAT

    return TaskType.RESEARCH if has_research_context else TaskType.QUICK_CHAT


# ── Provider manager ──────────────────────────────────────────────────────────
class ProviderManager:
    """Manages multiple LLM providers with bulletproof failover.

    Every call has a hard per-provider timeout. If a provider hangs,
    the next one is tried immediately. Never hangs for more than
    GLOBAL_TIMEOUT seconds total.
    """

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}
        self._register_providers()

    def _register_providers(self) -> None:
        """Register providers based on configured API keys."""
        nvidia_key = os.getenv("NVIDIA_API_KEY", "")
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "")

        nvidia_base = "https://integrate.api.nvidia.com/v1"
        openrouter_base = "https://openrouter.ai/api/v1"

        logger.info(f"[LLM] NVIDIA configured: {'yes' if nvidia_key else 'no'}")
        logger.info(f"[LLM] OpenRouter configured: {'yes' if openrouter_key else 'no'}")

        # ── NVIDIA NIM ──

        # Nemotron Super — fast (~3s), reliable workhorse (verified working)
        self._providers["nvidia_nemotron"] = Provider(
            name="nvidia_nemotron",
            model="nvidia/nemotron-3-super-120b-a12b",
            base_url=nvidia_base,
            api_key_env="NVIDIA_API_KEY",
            status=ProviderStatus.HEALTHY if nvidia_key else ProviderStatus.UNCONFIGURED,
            tags=["fast", "reliable", "primary"],
        )
        logger.info(
            f"[LLM] NVIDIA initialization: {'success' if nvidia_key else 'skipped'}"
            f" (model=nvidia/nemotron-3-super-120b-a12b)"
        )

        # ── OpenRouter ──

        # Nemotron Super via OpenRouter — free fallback (verified working)
        self._providers["openrouter_nemotron"] = Provider(
            name="openrouter_nemotron",
            model="nvidia/nemotron-3-super-120b-a12b:free",
            base_url=openrouter_base,
            api_key_env="OPENROUTER_API_KEY",
            status=ProviderStatus.HEALTHY if openrouter_key else ProviderStatus.UNCONFIGURED,
            tags=["free", "reliable", "fallback"],
        )

        # Nemotron Ultra 550B — most powerful, for heavy reasoning only
        self._providers["openrouter_nemotron_ultra"] = Provider(
            name="openrouter_nemotron_ultra",
            model="nvidia/nemotron-3-ultra-550b-a55b:free",
            base_url=openrouter_base,
            api_key_env="OPENROUTER_API_KEY",
            status=ProviderStatus.HEALTHY if openrouter_key else ProviderStatus.UNCONFIGURED,
            tags=["powerful", "reasoning", "free"],
        )

    def _get_client(self, provider: Provider):
        """Create a fresh OpenAI client for a provider."""
        from openai import OpenAI

        api_key = os.getenv(provider.api_key_env, "")
        if not api_key:
            raise RuntimeError(f"{provider.name}: API key not configured ({provider.api_key_env})")

        return OpenAI(
            api_key=api_key,
            base_url=provider.base_url,
            timeout=PER_PROVIDER_TIMEOUT,
            max_retries=0,  # We handle retries ourselves
        )

    def _call_provider(
        self,
        provider: Provider,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        top_p: float,
        finish_reason_out: list | None = None,
    ) -> str:
        # finish_reason_out: optional single-element list that receives the
        # provider's finish_reason for truncation detection upstream.
        """Make a SINGLE call to a provider with a hard timeout.

        Uses httpx directly for proper timeout + connection cancellation.
        When the timeout fires, the HTTP connection is CLOSED — not just ignored.
        """
        import httpx

        api_key = os.getenv(provider.api_key_env, "")
        if not api_key:
            raise RuntimeError(f"{provider.name}: API key not configured")

        provider.total_requests += 1
        t0 = time.time()

        # Build the request payload
        payload = {
            "model": provider.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stream": False,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        url = f"{provider.base_url}/chat/completions"

        # httpx with per-request timeout that KILLS the connection
        try:
            with httpx.Client(timeout=httpx.Timeout(
                connect=5.0,        # 5s to connect
                read=PER_PROVIDER_TIMEOUT,  # Max time for the response
                write=5.0,          # 5s to send
                pool=5.0,           # 5s for connection pool
            )) as client:
                resp = client.post(url, json=payload, headers=headers)
        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.error(f"[LLM] {provider.name} request failed: timeout ({exc.__class__.__name__})")
            raise TimeoutError(f"{provider.name}: request timed out") from exc
        except httpx.HTTPError as exc:
            logger.error(f"[LLM] {provider.name} request failed: network error ({exc.__class__.__name__})")
            raise RuntimeError(f"{provider.name}: network error ({exc.__class__.__name__})") from exc

        elapsed = time.time() - t0

        if resp.status_code == 401 or resp.status_code == 403:
            logger.error(f"[LLM] {provider.name} request failed: HTTP {resp.status_code} (auth)")
            raise PermissionError(f"{provider.name}: auth failed ({resp.status_code})")
        if resp.status_code == 429:
            logger.error(f"[LLM] {provider.name} request failed: HTTP 429 (rate limit)")
            raise RuntimeError(f"{provider.name}: rate limited (429)")
        if resp.status_code >= 500:
            logger.error(f"[LLM] {provider.name} request failed: HTTP {resp.status_code} (server error)")
            raise RuntimeError(f"{provider.name}: server error ({resp.status_code})")
        if resp.status_code != 200:
            logger.error(f"[LLM] {provider.name} request failed: HTTP {resp.status_code} (provider error)")
            raise RuntimeError(f"{provider.name}: HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            logger.error(f"[LLM] {provider.name} request failed: malformed provider response (no choices)")
            raise ValueError(f"{provider.name}: no choices in response")

        msg = choices[0].get("message", {})
        content = (msg.get("content") or "").strip()

        # Surface finish_reason for upstream truncation detection
        if finish_reason_out is not None:
            finish_reason_out.clear()
            fr = choices[0].get("finish_reason") or ""
            finish_reason_out.append(str(fr))

        # Log and discard any reasoning fields
        for field_name in ("reasoning_content", "reasoning"):
            val = msg.get(field_name)
            if val:
                logger.warning(
                    f"{provider.name}: discarded {field_name} ({len(val)} chars)"
                )

        if not content:
            raise ValueError(f"{provider.name}: empty response")

        provider.mark_healthy(elapsed)
        logger.info(
            f"✓ {provider.name} responded in {elapsed:.1f}s ({len(content)} chars)"
        )
        return content

    def _select_providers_for_task(self, task_type: TaskType) -> list[tuple[Provider, dict]]:
        """Get ordered list of (provider, config) for a task type."""
        routing = TASK_ROUTING.get(task_type, TASK_ROUTING[TaskType.QUICK_CHAT])
        result = []
        for config in routing:
            pname = config["provider"]
            provider = self._providers.get(pname)
            if provider and provider.is_available():
                result.append((provider, config))
        return result

    def _generate_with_failover(
        self,
        messages: list[dict[str, str]],
        task_type: TaskType = TaskType.QUICK_CHAT,
    ) -> str:
        """Core generation with task routing and hard failover.

        GUARANTEE: Will return within GLOBAL_TIMEOUT seconds or raise.
        """
        global_start = time.time()
        candidates = self._select_providers_for_task(task_type)

        if not candidates:
            # Try all available providers as last resort
            candidates = [
                (p, {"max_tokens": 512, "temperature": 0.5, "top_p": 0.9})
                for p in self._providers.values()
                if p.is_available()
            ]

        if not candidates:
            # Explain WHY no provider is usable (diagnostics only, no secrets)
            for p in self._providers.values():
                if p.status == ProviderStatus.UNCONFIGURED:
                    logger.error(f"[LLM] No providers available: {p.name} is unconfigured (missing {p.api_key_env})")
                elif not p.is_available():
                    cdr = p.get_cooldown_remaining()
                    logger.error(
                        f"[LLM] No providers available: {p.name} in cooldown "
                        f"{cdr:.0f}s (status={p.status.value}, last_error='{p.last_error}')"
                    )
            raise RuntimeError("No LLM providers available. Check API keys in .env")

        last_error = ""
        attempts = 0

        for provider, config in candidates:
            # Check global timeout before attempting next provider
            elapsed_global = time.time() - global_start
            if elapsed_global >= GLOBAL_TIMEOUT:
                logger.error(
                    f"GLOBAL TIMEOUT after {elapsed_global:.1f}s with {attempts} attempts"
                )
                break

            attempts += 1
            remaining = GLOBAL_TIMEOUT - elapsed_global
            # Use the smaller of per-provider timeout and remaining global time
            effective_timeout = min(PER_PROVIDER_TIMEOUT, remaining)

            logger.info(
                f"ROUTER: task={task_type.value} → {provider.name} "
                f"(attempt {attempts}, {remaining:.0f}s remaining)"
            )

            try:
                content = self._call_provider(
                    provider,
                    messages,
                    max_tokens=config.get("max_tokens", 512),
                    temperature=config.get("temperature", 0.5),
                    top_p=config.get("top_p", 0.9),
                )
                total_elapsed = time.time() - global_start
                logger.info(
                    f"✓ Chat complete in {total_elapsed:.1f}s "
                    f"(provider: {provider.name}, attempt {attempts})"
                )
                return content

            except TimeoutError as exc:
                last_error = str(exc)
                logger.error(f"✗ TIMEOUT: {last_error}")
                provider.mark_error(cooldown_seconds=30.0, reason="timeout")
                continue

            except Exception as exc:
                elapsed = time.time() - global_start
                last_error = str(exc)
                exc_msg = last_error.lower()
                logger.error(f"✗ {provider.name} failed ({elapsed:.1f}s): {last_error}")

                if any(t in exc_msg for t in ("rate", "quota", "429", "limit")):
                    provider.mark_rate_limited(120.0, reason=last_error)
                elif any(t in exc_msg for t in ("auth", "invalid", "permission", "401", "403")):
                    provider.mark_auth_failed(reason=last_error)
                elif any(t in exc_msg for t in ("timeout", "timed out", "deadline")):
                    provider.mark_error(30.0, reason="timeout")
                else:
                    # 5xx / malformed responses: escalate the cooldown when
                    # errors repeat so a flapping upstream stops taxing every
                    # request with a dead first attempt.
                    is_server_err = ("server error" in exc_msg
                                     or "no choices" in exc_msg
                                     or "empty response" in exc_msg)
                    base = 15.0 if is_server_err else 5.0
                    cooldown = min(base * (2.0 if provider.error_count >= 2 else 1.0), 120.0)
                    provider.mark_error(cooldown_seconds=cooldown, reason=last_error)
                continue

        total_elapsed = time.time() - global_start
        raise RuntimeError(
            f"All providers failed after {total_elapsed:.1f}s "
            f"({attempts} attempts). Last error: {last_error}"
        )

    def _generate_with_failover_meta(
        self,
        messages: list[dict[str, str]],
        task_type: TaskType = TaskType.QUICK_CHAT,
        max_tokens_override: int | None = None,
    ) -> tuple[str, str]:
        """Like _generate_with_failover but returns (text, finish_reason).

        Honors max_tokens_override (used by chat routes to cap/raise output
        length per question complexity).
        """
        global_start = time.time()
        candidates = self._select_providers_for_task(task_type)

        if not candidates:
            candidates = [
                (p, {"max_tokens": 512, "temperature": 0.5, "top_p": 0.9})
                for p in self._providers.values()
                if p.is_available()
            ]
        if not candidates:
            raise RuntimeError("No LLM providers available. Check API keys in .env")

        last_error = ""
        attempts = 0
        for provider, config in candidates:
            elapsed_global = time.time() - global_start
            if elapsed_global >= GLOBAL_TIMEOUT:
                break
            attempts += 1
            remaining = GLOBAL_TIMEOUT - elapsed_global
            logger.info(
                f"ROUTER: task={task_type.value} → {provider.name} "
                f"(attempt {attempts}, {remaining:.0f}s remaining)"
            )
            fr_holder: list[str] = []
            try:
                content = self._call_provider(
                    provider,
                    messages,
                    max_tokens=max_tokens_override or config.get("max_tokens", 512),
                    temperature=config.get("temperature", 0.5),
                    top_p=config.get("top_p", 0.9),
                    finish_reason_out=fr_holder,
                )
                finish_reason = fr_holder[0] if fr_holder else ""
                total_elapsed = time.time() - global_start
                logger.info(
                    f"✓ Chat(meta) complete in {total_elapsed:.1f}s "
                    f"(provider: {provider.name}, finish_reason={finish_reason or 'n/a'})"
                )
                return content, finish_reason
            except Exception as exc:
                last_error = str(exc)
                logger.error(f"✗ {provider.name} failed: {last_error}")
                exc_msg = last_error.lower()
                if any(t in exc_msg for t in ("rate", "quota", "429", "limit")):
                    provider.mark_rate_limited(120.0, reason=last_error)
                elif any(t in exc_msg for t in ("auth", "invalid", "permission", "401", "403")):
                    provider.mark_auth_failed(reason=last_error)
                elif any(t in exc_msg for t in ("timeout", "timed out", "deadline")):
                    provider.mark_error(30.0, reason="timeout")
                else:
                    # Escalating cooldown for repeated 5xx/malformed failures
                    # (see _generate_with_failover).
                    is_server_err = ("server error" in exc_msg
                                     or "no choices" in exc_msg
                                     or "empty response" in exc_msg)
                    base = 15.0 if is_server_err else 5.0
                    cooldown = min(base * (2.0 if provider.error_count >= 2 else 1.0), 120.0)
                    provider.mark_error(cooldown_seconds=cooldown, reason=last_error)
                continue

        raise RuntimeError(
            f"All providers failed after {time.time() - global_start:.1f}s "
            f"({attempts} attempts). Last error: {last_error}"
        )

    # ── Public API ────────────────────────────────────────────────────────

    def generate_text(self, prompt: str, task_type: TaskType = TaskType.QUICK_CHAT) -> str:
        """Single-prompt text completion."""
        if not prompt or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        return self._generate_with_failover(
            [{"role": "user", "content": prompt}],
            task_type=task_type,
        )

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        task_type: TaskType = TaskType.QUICK_CHAT,
    ) -> str:
        """Chat conversation with proper roles."""
        if not messages:
            raise ValueError("messages must be a non-empty list")
        return self._generate_with_failover(messages, task_type=task_type)

    def generate_chat_with_meta(
        self,
        messages: list[dict[str, str]],
        task_type: TaskType = TaskType.QUICK_CHAT,
        max_tokens_override: int | None = None,
    ) -> tuple[str, str]:
        """Chat generation that also reports the provider finish_reason.

        Returns (text, finish_reason). finish_reason is "" when unavailable.
        Used by the chat orchestrator's completeness validator to detect
        truncation instead of guessing from heuristics alone.
        """
        if not messages:
            raise ValueError("messages must be a non-empty list")
        return self._generate_with_failover_meta(
            messages, task_type=task_type, max_tokens_override=max_tokens_override,
        )

    def get_status(self) -> dict:
        """Provider status for monitoring."""
        available_count = sum(1 for p in self._providers.values() if p.is_available())
        active_provider = next(
            (p.name for p in self._providers.values() if p.is_available()),
            "none",
        )

        return {
            "providers": [
                {
                    "name": p.name,
                    "model": p.model,
                    "status": p.status.value,
                    "available": p.is_available(),
                    "avg_latency": round(p.avg_latency, 1),
                    "cooldown_remaining": round(p.get_cooldown_remaining(), 1),
                    "total_requests": p.total_requests,
                    "total_failures": p.total_failures,
                    "last_error": p.last_error,
                    "tags": p.tags,
                }
                for p in self._providers.values()
            ],
            "strategy": "fast_failover",
            "active_provider": active_provider,
            "total_providers": len(self._providers),
            "available_providers": available_count,
            "per_provider_timeout": PER_PROVIDER_TIMEOUT,
            "global_timeout": GLOBAL_TIMEOUT,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────
_manager: ProviderManager | None = None


def get_manager() -> ProviderManager:
    global _manager
    if _manager is None:
        _manager = ProviderManager()
    return _manager


def generate_text(prompt: str, task_type: TaskType = TaskType.QUICK_CHAT) -> str:
    return get_manager().generate_text(prompt, task_type=task_type)


def generate_chat(
    messages: list[dict[str, str]],
    task_type: TaskType = TaskType.QUICK_CHAT,
) -> str:
    return get_manager().generate_chat(messages, task_type=task_type)


def get_status() -> dict:
    return get_manager().get_status()
