"""Finora Chat Intelligence Engine.

Modular orchestration layer behind Finora Chat:
  router        — deterministic query classification (A–I categories)
  context_engine— session-context sufficiency + compact evidence pack
  calculator    — deterministic financial calculations with provenance
  retrieval     — targeted external retrieval (SEC/Tavily/Jina/market)
  validator     — answer-completeness detection + repair
  orchestrator  — pipeline glue used by /api/chat endpoints
"""
