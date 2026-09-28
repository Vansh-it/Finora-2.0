"""Live acceptance run (spec §37).

Builds a real Tesla research session through the ACTUAL Flask endpoints
(test client = real app code, real network calls to SEC/Tavily/Twelve Data/LLM),
then asks the 7 exact spec questions through /api/chat and reports
route, latency, sources, calculations, and the answer text.
"""

from __future__ import annotations

import io
import json
import logging
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(levelname)s %(name)s: %(message)s")

from app import app  # noqa: E402
from lib.persistence import load_research_sessions  # noqa: E402

client = app.test_client()

CHAT_LOG: list[str] = []


class ChatLogHandler(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if "[CHAT]" in msg:
            CHAT_LOG.append(msg)


logging.getLogger("finora.chat").addHandler(ChatLogHandler())
logging.getLogger("finora.chat.retrieval").addHandler(ChatLogHandler())


def post_json(path: str, payload: dict, timeout_hint: str = ""):
    resp = client.post(path, json=payload)
    try:
        data = resp.get_json()
    except Exception:
        data = {"raw": resp.get_data(as_text=True)[:500]}
    return resp.status_code, data


# Reuse the persisted Tesla session from a previous run if present
# (saves Tavily quota and LLM time during the pipeline phase).
_REUSE_SESSION_ID = ""
if "--reuse" in sys.argv:
    from lib.persistence import load_research_sessions as _lrs
    for _sid, _meta in _lrs().items():
        _cm = (_meta or {}).get("company_meta") or {}
        if _cm.get("ticker") == "TSLA":
            _REUSE_SESSION_ID = _sid
            break

if _REUSE_SESSION_ID:
    print(f"REUSING existing Tesla session: {_REUSE_SESSION_ID}")
    session_id = _REUSE_SESSION_ID
    pipeline_results = {"reused": {"ok": True, "s": 0, "err": ""}}
else:
    print("=" * 78)
    print("PHASE 1: Build real Tesla research session (live pipeline)")
    print("=" * 78)

    from lib.research_session import grant_permission  # noqa: E402

    sess = grant_permission({
        "company": "Tesla",
        "period_mode": "latest",
        "objective": "Live acceptance test for Finora Chat intelligence upgrade",
    }, user_id="")  # guest
    session_id = sess.session_id
    print(f"session_id = {session_id}")

    steps = [
        ("/api/research/fetch-filings", "fetch-filings"),
        ("/api/research/extract-financials", "extract-financials"),
        ("/api/research/calculate-metrics", "calculate-metrics"),
        ("/api/research/discover-sources", "discover-sources"),
        ("/api/research/read-verify-sources", "read-verify-sources"),
        ("/api/research/generate-summary", "generate-summary"),
        ("/api/research/calculate-valuation", "calculate-valuation"),
    ]
    pipeline_results = {}
    for path, name in steps:
        t0 = time.time()
        code, data = post_json(path, {"session_id": session_id})
        dt = time.time() - t0
        ok = code == 200
        err = data.get("error", "") if isinstance(data, dict) else ""
        pipeline_results[name] = {"ok": ok, "s": round(dt, 1), "err": err}
        print(f"  {name:<22} {'OK ' if ok else 'FAIL'} {dt:6.1f}s  {err[:90]}")

    completed = load_research_sessions().get(session_id, {})
    cm = completed.get("company_meta", {})
    print(f"\ncompany_meta: {cm.get('name')} ({cm.get('ticker')}), cik={cm.get('cik')}")
    fs = completed.get("financial_statements", {})
    print(f"periods: {fs.get('periods', [])}")
    is_ = fs.get("income_statement", {})
    for key in ("revenue", "operating_income", "net_income", "diluted_eps"):
        fact = is_.get(key, {})
        fy = sorted(fact.keys())[-1] if fact else "-"
        val = fact.get(fy, {}).get("value") if fact else None
        print(f"  {key:<18} {fy}: {val}")
    print(f"sources in registry: {len((completed.get('source_registry') or {}).get('sources', []))}")
    vm = (completed.get("valuation_metrics") or {}).get("valuation_metrics", {})
    print(f"valuation metrics: {sorted(vm.keys())[:8]}")
    md = completed.get("market_data", {})
    print(f"market_data: price={md.get('price')} date={md.get('price_date')} src={md.get('source')}")

# ══════════════════════════════════════════════════════════════════════════
# Phase 2 — The 7 exact acceptance questions (spec §37)
# ══════════════════════════════════════════════════════════════════════════

QUESTIONS = [
    "What was Tesla's revenue?",
    "What does the EPS tell me in simple words?",
    "Why did Tesla's revenue and operating income decrease?",
    "Who is Tesla's CEO and who are the members of its board?",
    "What is Tesla's current share price?",
    "Calculate Tesla's operating margin.",
    "Explain whether Tesla's profitability improved or deteriorated.",
]

print()
print("=" * 78)
print("PHASE 2: 7 acceptance questions via /api/chat (guest auth)")
print("=" * 78)

results = []
answers: dict[int, str] = {}
for i, q in enumerate(QUESTIONS, 1):
    CHAT_LOG.clear()
    t0 = time.time()
    code, data = post_json("/api/chat", {"message": q, "session_id": session_id, "history": []})
    wall = time.time() - t0
    ans = (data.get("response") or "") if isinstance(data, dict) else ""
    answers[i] = ans
    route = data.get("route", "?")
    repaired = data.get("repaired", "?")
    n_src = len(data.get("sources", []) or [])
    n_calc = len(data.get("calculations", []) or [])
    chars = len(ans)
    timings = " | ".join(CHAT_LOG[-3:])
    print(f"\nQ{i}: {q}")
    print(f"  HTTP {code} | route={route} | repaired={repaired} | "
          f"wall={wall:.2f}s | chars={chars} | sources={n_src} | calcs={n_calc}")
    print(f"  {timings}")
    if code != 200:
        print(f"  ERROR: {data}")
        results.append((q, route, wall, code, chars, n_src))
        continue
    print("  --- ANSWER ---")
    for line in ans.splitlines():
        print(f"  {line}")
    print("  --------------")
    results.append((q, route, wall, code, chars, n_src, n_calc))

# ══════════════════════════════════════════════════════════════════════════
# Phase 3 — Verification checks
# ══════════════════════════════════════════════════════════════════════════

print()
print("=" * 78)
print("PHASE 3: Verification checks")
print("=" * 78)

checks = []

# Fast-path routing correctness (no web research on fast paths)
expected_fast = {1: "context_lookup", 2: "interpretation", 6: "calculation"}
for idx, exp in expected_fast.items():
    got = results[idx - 1][1]
    checks.append((f"route Q{idx} == {exp}", got == exp, f"got {got}"))

# Completeness heuristics on captured answers
from lib.chat.validator import validate_answer
for idx, ans in answers.items():
    v = validate_answer(ans)
    checks.append((f"complete Q{idx}", v.ok, ",".join(v.reasons) or "clean"))

# Causal answer must not assert causation without evidence markers
causal_ans = answers.get(3, "").lower()
checks.append((
    "Q3 causal grounding",
    any(w in causal_ans for w in ("filing", "10-k", "per the", "management", "evidence",
                                   "according", "hypothes", "not conclusively")),
    causal_ans[:80],
))

print()
for name, ok, detail in checks:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  ({detail})")

# Save full transcripts
with io.open("_live_acceptance_transcript.json", "w", encoding="utf-8") as f:
    json.dump({"session_id": session_id, "pipeline": pipeline_results,
               "chat_log": CHAT_LOG,
               "results": [
                   {"q": r[0], "route": r[1], "wall_s": r[2], "http": r[3],
                    "chars": r[4], "sources": r[5],
                    "calcs": r[6] if len(r) > 6 else 0} for r in results],
               "answers": answers}, f, indent=2, ensure_ascii=False)
print(f"\nTranscript saved to _live_acceptance_transcript.json")
print(f"Session persisted: {session_id}")
