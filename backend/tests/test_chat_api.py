"""Unit tests for the POST /api/chat endpoint.

Covers: normal chat, empty message, malformed JSON, provider success,
primary failure + fallback success, all providers fail, long message.
Auth is not required — unauthenticated requests fall back to the guest user.
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app


@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _mock_auth():
    """Mock authenticated user — patches the auth lookup used by _get_auth_user."""
    from lib.auth_service import User
    mock_user = User(user_id="test_user_123", email="test@example.com", name="Test")
    return patch("app.get_user_from_token", return_value=mock_user)


def _auth_headers():
    """Return a fake Authorization header."""
    return {"Authorization": "Bearer fake_test_token"}


def _mock_generate(return_value: str = "Hello! I'm Finora."):
    """Patch manager.generate_chat to return a fixed string."""
    mock_manager = MagicMock()
    # Chat Intelligence Engine: orchestrator calls generate_chat_with_meta
    mock_manager.generate_chat_with_meta.return_value = (return_value, "stop")
    mock_manager.get_status.return_value = {
        "active_provider": "openai_oss",
        "providers": [{"name": "openai_oss", "available": True}],
    }
    return patch("app.get_manager", return_value=mock_manager)


def _mock_generate_error(error_msg: str = "All providers exhausted"):
    """Patch manager.generate_chat to raise RuntimeError."""
    mock_manager = MagicMock()
    mock_manager.generate_chat_with_meta.side_effect = RuntimeError(error_msg)
    mock_manager.get_status.return_value = {
        "active_provider": "none",
        "providers": [{"name": "openai_oss", "available": False}],
    }
    return patch("app.get_manager", return_value=mock_manager)


# ═════════════════════════════════════════════════════════════════════════════
# Normal requests (tests 1-3)
# ═════════════════════════════════════════════════════════════════════════════


class TestNormalChat:
    def test_01_normal_message(self, client):
        """Normal message returns response with success status."""
        with _mock_auth(), _mock_generate("Microsoft is a large tech company."):
            resp = client.post(
                "/api/chat",
                json={"message": "Tell me about Microsoft"},
                headers=_auth_headers(),
                content_type="application/json",
            )
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["response"] == "Microsoft is a large tech company."
        assert data["status"] == "success"
        assert "model_used" in data

    def test_02_message_with_history(self, client):
        """Message with history is accepted and returns response."""
        with _mock_auth(), _mock_generate("Yes, revenue grew 15%."):
            resp = client.post(
                "/api/chat",
                json={
                    "message": "Did revenue grow?",
                    "history": [
                        {"role": "user", "content": "Tell me about Microsoft"},
                        {"role": "assistant", "content": "Microsoft had a great year."},
                    ],
                },
                headers=_auth_headers(),
                content_type="application/json",
            )
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["status"] == "success"

    def test_03_empty_history_array(self, client):
        """Empty history array is accepted."""
        with _mock_auth(), _mock_generate("Hello!"):
            resp = client.post(
                "/api/chat",
                json={"message": "Hi", "history": []},
                headers=_auth_headers(),
                content_type="application/json",
            )
        assert resp.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# Validation (tests 4-7)
# ═════════════════════════════════════════════════════════════════════════════


class TestValidation:
    def test_04_empty_message(self, client):
        """Empty message returns 400."""
        with _mock_auth():
            resp = client.post(
                "/api/chat",
                json={"message": ""},
                headers=_auth_headers(),
                content_type="application/json",
            )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_05_missing_message_field(self, client):
        """Missing message field returns 400."""
        with _mock_auth():
            resp = client.post(
                "/api/chat",
                json={},
                headers=_auth_headers(),
                content_type="application/json",
            )
        assert resp.status_code == 400

    def test_06_malformed_json(self, client):
        """Malformed JSON returns 400."""
        with _mock_auth():
            resp = client.post(
                "/api/chat",
                data="not json",
                headers=_auth_headers(),
                content_type="application/json",
            )
        assert resp.status_code == 400

    def test_07_excessively_long_message(self, client):
        """Message exceeding max length returns 400."""
        with _mock_auth():
            long_msg = "A" * 3000
            resp = client.post(
                "/api/chat",
                json={"message": long_msg},
                headers=_auth_headers(),
                content_type="application/json",
            )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "too long" in data["error"].lower()


# ═════════════════════════════════════════════════════════════════════════════
# Auth enforcement (test 13)
# ═════════════════════════════════════════════════════════════════════════════


class TestGuestAccess:
    def test_13_no_auth_falls_back_to_guest(self, client):
        """Request without Authorization header is allowed and uses the guest user."""
        with _mock_generate("Hello! I'm Finora."):
            resp = client.post(
                "/api/chat",
                json={"message": "Hello"},
                content_type="application/json",
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["response"] == "Hello! I'm Finora."


# ═════════════════════════════════════════════════════════════════════════════
# Provider behavior (tests 8-10)
# ═════════════════════════════════════════════════════════════════════════════


class TestProviderBehavior:
    def test_08_provider_success(self, client):
        """Successful provider returns response text."""
        with _mock_auth(), _mock_generate("Revenue was $245B."):
            resp = client.post(
                "/api/chat",
                json={"message": "What was revenue?"},
                headers=_auth_headers(),
                content_type="application/json",
            )
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["response"] == "Revenue was $245B."

    def test_09_primary_provider_failure_fallback_succeeds(self, client):
        """When primary fails, failover succeeds."""
        mock_manager = MagicMock()
        mock_manager.generate_chat_with_meta.return_value = ("Fallback response.", "stop")
        mock_manager.get_status.return_value = {
            "active_provider": "nvidia_nemotron",
            "providers": [
                {"name": "openai_oss", "available": False},
                {"name": "nvidia_nemotron", "available": True},
            ],
        }
        with _mock_auth(), patch("app.get_manager", return_value=mock_manager):
            resp = client.post(
                "/api/chat",
                json={"message": "Hello"},
                headers=_auth_headers(),
                content_type="application/json",
            )
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["response"] == "Fallback response."

    def test_10_all_providers_fail(self, client):
        """All providers fail returns friendly error."""
        with _mock_auth(), _mock_generate_error("All providers exhausted"):
            resp = client.post(
                "/api/chat",
                json={"message": "Hello"},
                headers=_auth_headers(),
                content_type="application/json",
            )
        data = resp.get_json()
        assert resp.status_code == 502
        assert "temporarily unable" in data["error"].lower()
        assert data["status"] == "error"
        assert "traceback" not in json.dumps(data).lower()


# ═════════════════════════════════════════════════════════════════════════════
# Security (tests 11-12)
# ═════════════════════════════════════════════════════════════════════════════


class TestSecurity:
    def test_11_no_stack_trace_in_response(self, client):
        """Error responses must never contain stack traces."""
        with _mock_auth(), _mock_generate_error("Some internal error"):
            resp = client.post(
                "/api/chat",
                json={"message": "test"},
                headers=_auth_headers(),
                content_type="application/json",
            )
        raw = resp.get_data(as_text=True)
        assert "traceback" not in raw.lower()
        assert "File \"" not in raw

    def test_12_whitespace_only_message_rejected(self, client):
        """Whitespace-only message is rejected."""
        with _mock_auth():
            resp = client.post(
                "/api/chat",
                json={"message": "   "},
                headers=_auth_headers(),
                content_type="application/json",
            )
        assert resp.status_code == 400
