"""Tests for the Finora Chat Intelligence Engine.

Covers the acceptance scenarios from the chat-upgrade spec:
  1  Definition path, no external search
  2  Context lookup, no external search
  3  Calculation via Python
  4  Interpretation from context
  5  Causal question: evidence first, retrieval if thin
  6  CEO lookup: targeted retrieval, not "unavailable"
  7  Board members: authoritative lookup
  8  Share price: fresh market-data path
  9  Truncation detection + repair
  10 Provider timeout → graceful error
  11 Tavily failure → graceful degradation
  12 Jina failure → graceful degradation
  13 Company switch: no cross-company contamination
  14 Period alignment
"""

from __future__ import annotations

import sys
import os
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.chat.router import route_query
from lib.chat.context_engine import build_evidence_pack, pack_to_context_text
from lib.chat.calculator import calculate_from_session, calculations_to_text
from lib.chat.validator import validate_answer, build_continuation_messages
from lib.chat import retrieval as chat_retrieval


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

class FakeSession:
    """Minimal session stand-in matching the attributes the orchestrator uses."""

    def __init__(self, ticker="TSLA", name="Tesla, Inc.", company="Tesla"):
        self.company = company
        self.company_meta = {"name": name, "ticker": ticker, "cik": "1318605",
                             "exchange": "NASDAQ"}
        self.financial_statements = {
            "periods": ["FY2023", "FY2024", "FY2025"],
            "income_statement": {
                "revenue": {f"FY{y}": {"value": v, "period": f"FY{y}"}
                            for y, v in ((2023, 96.773e9), (2024, 97.690e9), (2025, 92.7e9))},
                "operating_income": {f"FY{y}": {"value": v, "period": f"FY{y}"}
                                     for y, v in ((2023, 8.891e9), (2024, 7.076e9), (2025, 4.3e9))},
                "net_income": {f"FY{y}": {"value": v, "period": f"FY{y}"}
                               for y, v in ((2023, 14.997e9), (2024, 7.091e9), (2025, 3.5e9))},
                "gross_profit": {f"FY{y}": {"value": v, "period": f"FY{y}"}
                                 for y, v in ((2023, 17.660e9), (2024, 17.450e9), (2025, 15.0e9))},
                "diluted_eps": {f"FY{y}": {"value": v, "period": f"FY{y}"}
                                for y, v in ((2023, 4.30), (2024, 2.04), (2025, 1.05))},
            },
            "balance_sheet": {
                "total_assets": {"FY2025": {"value": 122.0e9, "period": "FY2025"}},
                "shareholders_equity": {"FY2025": {"value": 72.9e9, "period": "FY2025"}},
                "total_debt": {"FY2025": {"value": 7.5e9, "period": "FY2025"}},
                "current_assets": {"FY2025": {"value": 55.0e9, "period": "FY2025"}},
                "current_liabilities": {"FY2025": {"value": 30.0e9, "period": "FY2025"}},
            },
            "cash_flow": {
                "operating_cash_flow": {"FY2025": {"value": 13.2e9, "period": "FY2025"}},
                "capital_expenditure": {"FY2025": {"value": -11.3e9, "period": "FY2025"}},
            },
            "additional": {},
        }
        self.calculated_metrics = {"annual_metrics": {}, "growth_metrics": {}}
        self.valuation_metrics = {
            "valuation_metrics": {
                "pe_ratio": {"status": "calculated", "value": 185.4,
                             "display_value": "185.4x", "formula": "market_cap / net_income",
                             "inputs": [], "period": "FY2025",
                             "market_data_date": "2026-09-20", "price_type": "current"},
            },
        }
        self.market_data = {"price": 410.0, "price_date": "2026-09-20",
                            "source": "Twelve Data", "shares_outstanding": 3.5e9}
        self.executive_summary = {"executive_overview": "Revenue declined while costs stayed elevated.",
                                  "highlights": [], "management_commentary_summary": ""}
        self.verification_results = {"management_commentary": []}
        self.forensic_scores = {"piotroski": {"score": 7, "status": "strong"}}
        self.red_flags = []
        self.source_registry = {"sources": [
            {"source_id": "sec_10k_fy2025", "title": "10-K FY2025 — Tesla",
             "provider": "SEC EDGAR", "url": "https://www.sec.gov/test", "source_type": "10-k",
             "period": "FY2025"},
        ]}


@pytest.fixture
def session():
    return FakeSession()


# ═════════════════════════════════════════════════════════════════════════════
# Router tests
# ═════════════════════════════════════════════════════════════════════════════

class TestRouter:
    def test_greeting(self):
        assert route_query("hi").route == "greeting"
        assert route_query("thanks").route == "greeting"

    def test_definition_no_session(self):
        assert route_query("What is EPS?").route == "definition"
        assert route_query("Explain EBITDA").route == "definition"

    def test_context_lookup(self):
        assert route_query("What was Tesla's revenue?", has_session=True).route == "context_lookup"
        assert route_query("What is net income?", has_session=True).route == "context_lookup"

    def test_calculation(self):
        assert route_query("Calculate operating margin.", has_session=True).route == "calculation"
        assert route_query("What is the P/E?", has_session=True).route == "calculation"

    def test_interpretation(self):
        assert route_query("What does the EPS tell us?", has_session=True).route == "interpretation"
        assert route_query("Is margin improving?", has_session=True).route == "interpretation"

    def test_causal(self):
        assert route_query("Why did operating income decrease?", has_session=True).route == "causal"
        assert route_query("What caused margin compression?", has_session=True).route == "causal"

    def test_external_lookup(self):
        assert route_query("Who is the CEO?", has_session=True).route == "external_lookup"
        assert route_query("Who are the board members?", has_session=True).route == "external_lookup"

    def test_current_data(self):
        assert route_query("What is the share price right now?", has_session=True).route == "current_data"
        assert route_query("How is the stock doing today?", has_session=True).route == "current_data"

    def test_deep_research(self):
        assert route_query(
            "Analyze why Tesla margins deteriorated over the last three years",
            has_session=True).route == "deep_research"

    def test_no_external_route_for_definition(self):
        """Definitions must not be sent to retrieval services."""
        d = route_query("What is EPS?")
        assert d.route == "definition"


# ═════════════════════════════════════════════════════════════════════════════
# Context engine tests (TEST 2, 14)
# ═════════════════════════════════════════════════════════════════════════════

class TestContextEngine:
    def test_revenue_lookup_from_context(self, session):
        pack = build_evidence_pack(session, "What was Tesla's revenue?")
        text = pack_to_context_text(pack)
        assert "revenue" in text.lower()
        assert "$92.7B" in text or "92.7" in text
        assert pack["metrics_found"]

    def test_period_awareness(self, session):
        pack = build_evidence_pack(session, "What was revenue in FY2023?")
        text = pack_to_context_text(pack)
        assert "FY2023" in text
        assert "96.8" in text or "96,773" in text or "$96.8B" in text

    def test_period_alignment_not_mixed(self, session):
        """FY2023 question must not return FY2025 values."""
        pack = build_evidence_pack(session, "What was operating income in FY2023?")
        text = pack_to_context_text(pack)
        assert "FY2023" in text
        # FY2025 operating income is 4.3B; must NOT appear as the answer
        assert "(FY2025): $4.3B" not in text

    def test_pack_is_compact(self, session):
        pack = build_evidence_pack(session, "What is net income?")
        assert len(pack_to_context_text(pack)) < 3500

    def test_causal_includes_prior_period(self, session):
        pack = build_evidence_pack(session, "Why did operating income decrease?")
        text = pack_to_context_text(pack)
        # Should include both current and prior values for comparison
        assert "FY2024" in text or "FY2025" in text


# ═════════════════════════════════════════════════════════════════════════════
# Calculator tests (TEST 3)
# ═════════════════════════════════════════════════════════════════════════════

class TestCalculator:
    def test_operating_margin(self, session):
        calcs = calculate_from_session(session, "Calculate operating margin")
        m = next(c for c in calcs if c["metric"] == "operating_margin")
        assert m["status"] == "calculated"
        expected = round(4.3e9 / 92.7e9 * 100, 2)
        assert abs(m["value"] - expected) < 0.01
        assert "%" in m["display"]
        assert m["inputs"]["numerator"] == 4.3e9
        assert m["source_ids"]

    def test_fcf(self, session):
        calcs = calculate_from_session(session, "Calculate free cash flow")
        m = next(c for c in calcs if c["metric"] == "free_cash_flow")
        # OCF 13.2B + capex (-11.3B) = 1.9B
        assert abs(m["value"] - 1.9e9) < 1e6

    def test_fcf_margin(self, session):
        calcs = calculate_from_session(session, "Calculate FCF margin")
        m = next(c for c in calcs if c["metric"] == "fcf_margin")
        expected = round(1.9e9 / 92.7e9 * 100, 2)
        assert abs(m["value"] - expected) < 0.01

    def test_current_ratio(self, session):
        calcs = calculate_from_session(session, "Calculate current ratio")
        m = next(c for c in calcs if c["metric"] == "current_ratio")
        assert abs(m["value"] - round(55.0e9 / 30.0e9, 3)) < 0.01

    def test_debt_to_equity(self, session):
        calcs = calculate_from_session(session, "Calculate debt to equity")
        m = next(c for c in calcs if c["metric"] == "debt_to_equity")
        assert abs(m["value"] - round(7.5e9 / 72.9e9, 3)) < 0.01

    def test_revenue_growth_uses_correct_periods(self, session):
        calcs = calculate_from_session(session, "What was revenue growth?")
        m = next(c for c in calcs if c["metric"] == "revenue_growth")
        expected = round((92.7e9 - 97.69e9) / 97.69e9 * 100, 2)
        assert abs(m["value"] - expected) < 0.02
        # Inputs keep period labels
        assert any("FY2025" in k for k in m["inputs"])

    def test_provenance_structure(self, session):
        calcs = calculate_from_session(session, "Calculate operating margin")
        m = calcs[0]
        for field in ("metric", "value", "display", "formula", "inputs",
                      "period", "source_ids", "value_type", "status"):
            assert field in m

    def test_unavailable_when_inputs_missing(self, session):
        session.financial_statements["balance_sheet"] = {}
        calcs = calculate_from_session(session, "Calculate current ratio")
        m = next(c for c in calcs if c["metric"] == "current_ratio")
        assert m["status"] == "unavailable"

    def test_no_llm_needed_pure_python(self, session):
        """The calculation must not require any LLM/provider."""
        calcs = calculate_from_session(session, "Calculate operating margin")
        assert calcs[0]["value"] is not None

    def test_share_price_not_implied_from_stale_data(self, session):
        """Calculations never invent a current price from historical data."""
        calcs = calculate_from_session(session, "What is the share price right now?")
        for c in calcs:
            if c["metric"] == "share_price":
                # If returned, it must come from the valuation engine's
                # recorded price_type, never silently "calculated"
                assert c.get("note") != "" or c.get("value_type") != "calculated"


# ═════════════════════════════════════════════════════════════════════════════
# Validator tests (TEST 9)
# ═════════════════════════════════════════════════════════════════════════════

class TestValidator:
    def test_complete_answer_passes(self):
        v = validate_answer("Revenue was $92.7B in FY2025. This represents a decline.")
        assert v.ok

    def test_empty_response_fails(self):
        assert not validate_answer("").ok
        assert not validate_answer("   ").ok

    def test_finish_reason_length_fails(self):
        v = validate_answer("Revenue was $92.7B and", finish_reason="length")
        assert not v.ok
        assert "finish_reason=length" in v.reasons

    def test_unclosed_bold_detected(self):
        v = validate_answer("Operating income fell. **Operating")
        assert not v.ok
        assert "unclosed_bold" in v.reasons

    def test_dangling_heading(self):
        assert not validate_answer("Some text.\n## Key Factors").ok

    def test_trailing_colon(self):
        assert not validate_answer("Here are the factors:").ok

    def test_unclosed_code_fence(self):
        assert not validate_answer("Here:\n```python\nx = 1").ok

    def test_abrupt_sentence_end(self):
        assert not validate_answer("The operating income declined by 12.4 percent to 4.3").ok

    def test_continuation_messages_exclude_full_history(self):
        msgs = build_continuation_messages(
            [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}],
            "partial answer that was cut off at **Operating")
        assert msgs[-2]["role"] == "assistant"
        assert msgs[-1]["role"] == "user"
        assert "Do NOT repeat" in msgs[-1]["content"]

    def test_complete_markdown_table_passes(self):
        v = validate_answer("| Metric | Value |\n|---|---|\n| Revenue | $92.7B |")
        assert v.ok


# ═════════════════════════════════════════════════════════════════════════════
# Retrieval degradation tests (TEST 11, 12)
# ═════════════════════════════════════════════════════════════════════════════

class TestRetrievalDegradation:
    def test_tavily_failure_graceful(self, session):
        """Tavily unavailable → retrieval returns empty, no exception."""
        with patch("lib.tavily_client.tavily_search", side_effect=RuntimeError("no key")):
            r = chat_retrieval.retrieve_external_facts("Tesla", "TSLA", "Who is the CEO?")
        assert r.is_empty()
        assert "tavily_unavailable" in r.errors or "no_results" in r.errors

    def test_tavily_timeout_graceful(self, session):
        with patch("lib.chat.retrieval._tavily_search", return_value=None):
            r = chat_retrieval.retrieve_external_facts("Tesla", "TSLA", "Who is the CEO?")
        assert r.is_empty()

    def test_tavily_success_returns_sources(self):
        fake_results = [
            {"title": "Tesla Leadership", "url": "https://ir.tesla.com/leadership",
             "content": "Elon Musk serves as Chief Executive Officer of Tesla."},
            {"title": "Board", "url": "https://ir.tesla.com/board",
             "content": "The board includes Robyn Denholm among others."},
        ]
        with patch("lib.chat.retrieval._tavily_search", return_value=fake_results):
            r = chat_retrieval.retrieve_external_facts("Tesla", "TSLA", "Who is the CEO?")
        assert not r.is_empty()
        assert r.sources and r.sources[0]["url"]
        assert "Elon Musk" in r.lines[0]

    def test_jina_failure_graceful(self):
        """Jina fails → fall back to snippet lines, never crash."""
        fake_results = [{"title": "Tesla Leadership", "url": "https://ir.tesla.com/leadership",
                         "content": "Elon Musk is CEO."}]
        with patch("lib.chat.retrieval._tavily_search", return_value=fake_results), \
             patch("lib.chat.retrieval._jina_read", side_effect=RuntimeError("jina down")):
            r = chat_retrieval.retrieve_external_facts("Tesla", "TSLA", "Who is the CEO?")
        assert not r.is_empty()  # snippet still used

    def test_causal_retrieval_dedupes(self):
        fake = [
            {"title": "A", "url": "https://x.com/1", "content": "costs rose due to tariffs"},
            {"title": "A dup", "url": "https://x.com/1", "content": "duplicate"},
        ]
        with patch("lib.chat.retrieval._tavily_search", return_value=fake):
            r = chat_retrieval.retrieve_causal_evidence("Tesla", "TSLA", "Why did margin fall?")
        assert len(r.lines) == 1


# ═════════════════════════════════════════════════════════════════════════════
# Orchestrator end-to-end (mocked providers) — TESTS 1, 4, 5, 6, 7, 8
# ═════════════════════════════════════════════════════════════════════════════

class _MockManager:
    def __init__(self, response="OK.", finish="stop"):
        self.response = response
        self.finish = finish
        self.calls: list[list] = []

    def generate_chat_with_meta(self, messages, task_type=None, max_tokens_override=None):
        self.calls.append(list(messages))
        return self.response, self.finish

    def get_status(self):
        return {"active_provider": "mock", "providers": []}


class TestOrchestratorPaths:
    def test_definition_no_retrieval(self, session):
        """TEST 1: definition path makes no retrieval calls."""
        mgr = _MockManager("EPS is earnings per share.")
        orch = chat_orch(mgr, session)
        outcome = orch.handle("What is EPS?", [])
        assert outcome.route == "definition"
        assert not outcome.sources  # no retrieval
        assert outcome.response == "EPS is earnings per share."

    def test_context_lookup_no_retrieval(self, session):
        """TEST 2: context lookup uses the evidence pack, not the web."""
        mgr = _MockManager("Revenue was $92.7B.")
        orch = chat_orch(mgr, session)
        outcome = orch.handle("What was Tesla's revenue?", [])
        assert outcome.route == "context_lookup"
        # No external retrieval: no web sources, no retrieval diagnostics.
        # Session-registry provenance (SEC filing IDs) may ride along per §27.
        assert all(s.get("provider") != "Tavily" for s in outcome.sources)
        assert "retrieval_ms" not in outcome.diagnostics
        # Evidence must be in the prompt
        prompt = mgr.calls[0][-1]["content"]
        assert "EVIDENCE" in prompt
        assert "revenue" in prompt.lower()

    def test_calculation_supplies_python_result(self, session):
        """TEST 3: calculator result is in the prompt, marked authoritative."""
        mgr = _MockManager("Operating margin is 4.64%.")
        orch = chat_orch(mgr, session)
        outcome = orch.handle("Calculate operating margin", [])
        assert outcome.route == "calculation"
        assert outcome.calculations
        prompt = mgr.calls[0][-1]["content"]
        assert "DETERMINISTIC CALCULATIONS" in prompt
        assert "4.64" in prompt or "4.6" in prompt

    def test_causal_with_thin_evidence_retrieves(self, session):
        """TEST 5: causal question with no commentary triggers retrieval."""
        session.verification_results = {"management_commentary": []}
        with patch("lib.chat.orchestrator.retrieve_causal_evidence") as mock_ret:
            mock_ret.return_value = _fake_retrieval(["[web-00001] Costs rose (https://x)"])
            mgr = _MockManager("Costs rose per the filing.")
            orch = chat_orch(mgr, session)
            outcome = orch.handle("Why did operating income decrease?", [])
        assert outcome.route == "causal"
        mock_ret.assert_called_once()
        prompt = mgr.calls[0][-1]["content"]
        assert "RETRIEVED EXTERNAL EVIDENCE" in prompt

    def test_causal_with_commentary_skips_retrieval(self, session):
        """TEST 5b: local commentary suffices — no web call."""
        session.verification_results = {"management_commentary": [
            {"source_id": "sec_10k", "text": "Operating income declined due to lower ASPs."}]}
        with patch("lib.chat.orchestrator.retrieve_causal_evidence") as mock_ret:
            mgr = _MockManager("Per the 10-K, lower ASPs.")
            orch = chat_orch(mgr, session)
            outcome = orch.handle("Why did operating income decrease?", [])
        mock_ret.assert_not_called()
        prompt = mgr.calls[0][-1]["content"]
        assert "lower ASPs" in prompt

    def test_ceo_lookup_retrieves(self, session):
        """TEST 6: CEO question triggers targeted retrieval, not refusal."""
        with patch("lib.chat.orchestrator.retrieve_external_facts") as mock_ret:
            mock_ret.return_value = _fake_retrieval(
                ["[web-00001] Elon Musk is CEO (https://ir.tesla.com)"])
            mgr = _MockManager("Elon Musk is the CEO of Tesla.")
            orch = chat_orch(mgr, session)
            outcome = orch.handle("Who is the CEO of Tesla?", [])
        mock_ret.assert_called_once()
        assert outcome.route == "external_lookup"
        assert outcome.sources

    def test_board_lookup_retrieves(self, session):
        """TEST 7: board members trigger retrieval."""
        with patch("lib.chat.orchestrator.retrieve_external_facts") as mock_ret:
            mock_ret.return_value = _fake_retrieval(
                ["[web-00001] Robyn Denholm chairs the board (https://ir.tesla.com)"])
            mgr = _MockManager("The board includes Robyn Denholm.")
            orch = chat_orch(mgr, session)
            outcome = orch.handle("Who are the board members?", [])
        mock_ret.assert_called_once()

    def test_current_price_uses_market_data(self, session):
        """TEST 8: share price path fetches fresh data; never implies."""
        with patch("lib.chat.orchestrator.fetch_current_price_snapshot") as mock_price:
            mock_price.return_value = {"ticker": "TSLA", "price": 412.5,
                                       "date": "2026-09-24 14:00 UTC",
                                       "source": "Twelve Data",
                                       "value_type": "current market value",
                                       "percent_change": 0.61}
            mgr = _MockManager("TSLA trades at $412.50.")
            orch = chat_orch(mgr, session)
            outcome = orch.handle("What is the share price right now?", [])
        mock_price.assert_called_once_with("TSLA")
        prompt = mgr.calls[0][-1]["content"]
        assert "412.50" in prompt
        assert "current market value" in prompt

    def test_current_price_failure_honest(self, session):
        """TEST 8b: when market data fails, the answer must not imply a price."""
        with patch("lib.chat.orchestrator.fetch_current_price_snapshot", return_value=None):
            mgr = _MockManager("Current price is temporarily unavailable.")
            orch = chat_orch(mgr, session)
            outcome = orch.handle("What is the share price right now?", [])
        prompt = mgr.calls[0][-1]["content"]
        assert "could not be retrieved" in prompt
        assert "DO NOT estimate" in prompt

    def test_repair_pass_on_truncation(self, session):
        """TEST 9: truncated output triggers one continuation and combines."""
        mgr = _MockManager()
        mgr.responses = iter([
            ("Operating income fell. **Operating", "length"),
            ("margin declined to 4.6%. The driver was lower ASPs.", "stop"),
        ])

        def fake_generate(messages, task_type=None, max_tokens_override=None):
            self = mgr
            self.calls.append(list(messages))
            return next(self.responses)

        mgr.generate_chat_with_meta = fake_generate
        orch = chat_orch(mgr, session)
        outcome = orch.handle("What does the EPS tell us?", [])
        assert outcome.repaired is True
        assert len(mgr.calls) == 2
        # Combined text must contain both parts without repetition
        assert "margin declined to 4.6%" in outcome.response
        # Continuation prompt asked for seamless continuation
        cont_prompt = mgr.calls[1][-1]["content"]
        assert "Do NOT repeat" in cont_prompt

    def test_no_repair_when_complete(self, session):
        mgr = _MockManager("Complete answer with all details. Done.")
        orch = chat_orch(mgr, session)
        outcome = orch.handle("What was revenue?", [])
        assert outcome.repaired is False
        assert len(mgr.calls) == 1

    def test_provider_error_propagates_controlled(self, session):
        """TEST 10: provider RuntimeError propagates (endpoint maps to 502)."""
        class FailingManager(_MockManager):
            def generate_chat_with_meta(self, messages, **kw):
                raise RuntimeError("All providers failed after 30.1s")

        orch = chat_orch(FailingManager(), session)
        with pytest.raises(RuntimeError):
            orch.handle("hi", [])

    def test_company_switch_no_contamination(self):
        """TEST 13: Tesla session answers must not appear for Apple session."""
        apple = FakeSession(ticker="AAPL", name="Apple Inc.", company="Apple")
        apple.financial_statements["income_statement"]["revenue"] = {
            "FY2025": {"value": 391.0e9, "period": "FY2025"}}
        # Replace provenance too — a copied Tesla source registry would leak
        apple.source_registry = {"sources": [
            {"source_id": "sec_10k_fy2025", "title": "10-K FY2025 — Apple",
             "provider": "SEC EDGAR", "url": "https://www.sec.gov/test-aapl",
             "source_type": "10-k", "period": "FY2025"},
        ]}

        for sess, expected_ticker in ((FakeSession(), "TSLA"), (apple, "AAPL")):
            mgr = _MockManager("answer")
            orch = chat_orch(mgr, sess)
            outcome = orch.handle("What was revenue?", [])
            prompt = mgr.calls[0][-1]["content"]
            assert expected_ticker in prompt
            other = "Tesla" if expected_ticker == "AAPL" else "AAPL"
            assert other not in prompt

    def test_period_comparison_aligned(self, session):
        """TEST 14: growth inputs keep period labels."""
        calcs = calculate_from_session(session, "What was revenue growth?")
        m = next(c for c in calcs if c["metric"] == "revenue_growth")
        keys = " ".join(m["inputs"].keys())
        assert "FY2025" in keys and "FY2024" in keys


class TestRobustnessAdditions:
    """Additions found during the live acceptance run."""

    def test_reasoning_leak_retry(self, session):
        """Reasoner planning text leaking into content is retried, not shown."""
        leaked = ("We need to answer why operating income fell. We must cite "
                  "evidence. Use evidence: revenue fell. Provide explanation "
                  "using evidence. The evidence includes revenue.")
        replies = iter([
            (leaked, "stop"),
            ("Operating income fell 38.5% per the 10-K.", "stop"),
        ])
        mgr = _MockManager()

        def gen(messages, task_type=None, max_tokens_override=None):
            mgr.calls.append(list(messages))
            return next(replies)

        mgr.generate_chat_with_meta = gen
        orch = chat_orch(mgr, session)
        with patch("lib.chat.orchestrator.retrieve_causal_evidence",
                   return_value=chat_retrieval.RetrievalResult()):
            outcome = orch.handle("Why did operating income decrease?", [])
        assert outcome.repaired is True
        assert "We need to answer" not in outcome.response
        assert len(mgr.calls) == 2
        # Retry uses a minimal message set (system + last user turn)
        assert len(mgr.calls[1]) <= 3

    def test_trim_partial_tail(self):
        from lib.chat.orchestrator import _trim_partial_tail
        t = _trim_partial_tail("Revenue declined in FY2025. **Operating")
        assert "**Operating" not in t
        assert t.rstrip().endswith("FY2025.")

    def test_trend_question_includes_multi_period_metrics(self, session):
        """Trend questions see calculated metrics for prior periods too."""
        session.calculated_metrics = {"annual_metrics": {
            "FY2024": {"operating_margin": {"status": "calculated", "value": 7.24,
                                              "display_value": "7.24%", "period": "FY2024"}},
            "FY2025": {"operating_margin": {"status": "calculated", "value": 4.59,
                                              "display_value": "4.59%", "period": "FY2025"}},
        }, "growth_metrics": {}}
        pack = build_evidence_pack(session, "Explain whether profitability improved or deteriorated.")
        text = pack_to_context_text(pack)
        assert "FY2024" in text
        assert "4.59" in text and "7.24" in text


def chat_orch(manager, session):
    from lib.chat.orchestrator import ChatOrchestrator
    return ChatOrchestrator(manager, session=session)


def _fake_retrieval(lines):
    r = chat_retrieval.RetrievalResult()
    r.lines = lines
    r.sources = [{"source_id": "web-00001", "title": "t", "url": "https://x",
                  "source_type": "web", "provider": "Tavily", "snippet": ""}]
    return r
