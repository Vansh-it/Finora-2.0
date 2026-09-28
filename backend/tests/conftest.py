"""Shared test fixtures for the Finora backend test suite.

Chat usage limits are persisted to disk (data/chat_usage.json) and keyed by
the shared guest user, so tests that hit /api/chat can exhaust the 24h quota
of *later* tests (flaky 429s). An autouse fixture gives every test a clean
slate.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_chat_usage():
    """Isolate the shared guest chat quota between tests."""
    try:
        from lib.chat_usage import clear_all
        clear_all()
    except Exception:
        pass  # tests that never touch chat usage don't need this to succeed
    yield
