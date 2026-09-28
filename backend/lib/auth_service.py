"""Basic authentication service.

Provides sign-up, sign-in, sign-out, and session persistence using
JSON-file-backed storage with Werkzeug password hashing and simple
token-based auth. Designed to be provider-agnostic — swap the storage
backend later without rewriting Finora.

No social profiles, teams, orgs, subscriptions, or payment processing.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from werkzeug.security import generate_password_hash, check_password_hash

from lib.persistence import (
    save_user, load_users, save_auth_sessions, load_auth_sessions,
    save_email_index, load_email_index,
)

# ── In-memory stores (synced to disk) ────────────────────────────────────────
_users: dict[str, "User"] = {}
_sessions: dict[str, "Session"] = {}
_email_index: dict[str, str] = {}
_loaded = False


def _ensure_loaded() -> None:
    """Load persisted data into memory on first access."""
    global _loaded
    if _loaded:
        return
    _loaded = True

    # Load users
    raw_users = load_users()
    for uid, udata in raw_users.items():
        if isinstance(udata, dict):
            _users[uid] = User(
                user_id=udata.get("user_id", uid),
                email=udata.get("email", ""),
                name=udata.get("name", ""),
                password_hash=udata.get("password_hash", ""),
                created_at=udata.get("created_at", 0),
                research_runs_used=udata.get("research_runs_used", 0),
                research_runs_limit=udata.get("research_runs_limit", 5),
            )

    # Load email index
    _email_index.update(load_email_index())

    # Load auth sessions
    raw_sessions = load_auth_sessions()
    for token, sdata in raw_sessions.items():
        if isinstance(sdata, dict):
            _sessions[token] = Session(
                token=sdata.get("token", token),
                user_id=sdata.get("user_id", ""),
                created_at=sdata.get("created_at", 0),
                expires_at=sdata.get("expires_at", 0),
            )


def _persist_user(user: User) -> None:
    """Save a single user to disk."""
    save_user(user)


def _persist_all_users() -> None:
    """Save all users to disk."""
    raw = {}
    for uid, user in _users.items():
        raw[uid] = user.to_dict()
    from lib.persistence import save_users
    save_users(raw)


def _persist_sessions() -> None:
    """Save all auth sessions to disk."""
    raw = {}
    for token, sess in _sessions.items():
        raw[token] = {
            "token": sess.token,
            "user_id": sess.user_id,
            "created_at": sess.created_at,
            "expires_at": sess.expires_at,
        }
    save_auth_sessions(raw)


def _persist_email_index() -> None:
    """Save email index to disk."""
    save_email_index(dict(_email_index))


# ── Data classes ─────────────────────────────────────────────────────────────
@dataclass
class User:
    user_id: str = field(default_factory=lambda: secrets.token_hex(16))
    email: str = ""
    name: str = ""
    password_hash: str = ""
    created_at: float = field(default_factory=time.time)

    # Research usage limits
    research_runs_used: int = 0
    research_runs_limit: int = 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "name": self.name,
            "password_hash": self.password_hash,
            "created_at": self.created_at,
            "research_runs_used": self.research_runs_used,
            "research_runs_limit": self.research_runs_limit,
        }

    def to_public_dict(self) -> dict[str, Any]:
        """Return user dict without sensitive fields."""
        return {
            "user_id": self.user_id,
            "email": self.email,
            "name": self.name,
            "research_runs_used": self.research_runs_used,
            "research_runs_limit": self.research_runs_limit,
        }


@dataclass
class Session:
    token: str = field(default_factory=lambda: secrets.token_hex(32))
    user_id: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0  # 7 days by default

    def is_valid(self) -> bool:
        return time.time() < self.expires_at


# ── Password hashing ─────────────────────────────────────────────────────────
def _hash_password(password: str) -> str:
    """Hash a password using Werkzeug's PBKDF2 (SHA-256, 600k iterations)."""
    return generate_password_hash(password, method="pbkdf2:sha256", salt_length=16)


def _verify_password(password: str, stored: str) -> bool:
    """Verify a password against the stored hash."""
    try:
        return check_password_hash(stored, password)
    except Exception:
        return False


# ── Public API ───────────────────────────────────────────────────────────────
def sign_up(email: str, password: str, name: str = "") -> dict[str, Any]:
    """Create a new user account. Returns user dict + auth token."""
    _ensure_loaded()
    email = email.strip().lower()
    if not email or not password:
        raise ValueError("Email and password are required")
    if email in _email_index:
        raise ValueError("An account with this email already exists")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    user = User(
        email=email,
        name=name.strip(),
        password_hash=_hash_password(password),
    )
    _users[user.user_id] = user
    _email_index[email] = user.user_id

    session = _create_session(user.user_id)

    # Persist to disk
    _persist_user(user)
    _persist_email_index()
    _persist_sessions()

    return {"user": user.to_public_dict(), "token": session.token}


def sign_in(email: str, password: str) -> dict[str, Any]:
    """Authenticate an existing user. Returns user dict + auth token."""
    _ensure_loaded()
    email = email.strip().lower()
    user_id = _email_index.get(email)
    if not user_id:
        raise ValueError("No account found with this email")

    user = _users[user_id]
    if not _verify_password(password, user.password_hash):
        raise ValueError("Incorrect password")

    session = _create_session(user.user_id)

    # Persist session
    _persist_sessions()

    return {"user": user.to_public_dict(), "token": session.token}


def get_user_from_token(token: str) -> Optional[User]:
    """Look up a user by session token. Returns None if invalid/expired."""
    _ensure_loaded()
    session = _sessions.get(token)
    if session is None or not session.is_valid():
        return None
    return _users.get(session.user_id)


GUEST_USER_ID = "guest"


def get_guest_user() -> User:
    """Return the shared anonymous user used for unauthenticated access."""
    _ensure_loaded()
    user = _users.get(GUEST_USER_ID)
    if user is None:
        user = User(
            user_id=GUEST_USER_ID,
            email="",
            name="Guest",
            research_runs_limit=100000,
        )
        _users[GUEST_USER_ID] = user
        _persist_user(user)
    return user


def sign_out(token: str) -> bool:
    """Invalidate a session. Returns True if found."""
    _ensure_loaded()
    if token in _sessions:
        del _sessions[token]
        _persist_sessions()
        return True
    return False


def increment_research_runs(user_id: str) -> bool:
    """Increment research_runs_used for a user. Returns True if under limit."""
    _ensure_loaded()
    user = _users.get(user_id)
    if user is None:
        return False
    if user.research_runs_used >= user.research_runs_limit:
        return False
    user.research_runs_used += 1
    _persist_user(user)
    return True


def can_use_research(user_id: str) -> dict[str, Any]:
    """Check if user can start a research run."""
    _ensure_loaded()
    user = _users.get(user_id)
    if user is None:
        return {"allowed": False, "remaining": 0, "limit": 5, "reason": "User not found"}
    remaining = max(0, user.research_runs_limit - user.research_runs_used)
    return {
        "allowed": remaining > 0,
        "remaining": remaining,
        "limit": user.research_runs_limit,
        "used": user.research_runs_used,
    }


def get_user(user_id: str) -> Optional[User]:
    """Look up a user by ID."""
    _ensure_loaded()
    return _users.get(user_id)


def clear_all() -> None:
    """Drop all users and sessions — useful for tests."""
    global _loaded
    _users.clear()
    _sessions.clear()
    _email_index.clear()
    _loaded = False
    from lib.persistence import clear_all_persistence
    clear_all_persistence()


# ── Internal helpers ─────────────────────────────────────────────────────────
def _create_session(user_id: str) -> Session:
    """Create a new session token valid for 7 days."""
    session = Session(
        user_id=user_id,
        expires_at=time.time() + 7 * 24 * 3600,
    )
    _sessions[session.token] = session
    return session
