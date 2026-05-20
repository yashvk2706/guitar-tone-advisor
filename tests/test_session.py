"""Session store tests — Phase 3. 3 offline unit tests. No live-DB required."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_sessions():
    """Clear module-level _sessions dict before and after every test so session
    state cannot bleed between tests."""
    import app.session as s

    s._sessions.clear()
    yield
    s._sessions.clear()


# ---------------------------------------------------------------------------
# CHAT-02: Session store unit tests
# ---------------------------------------------------------------------------


def test_get_or_create_creates_new_session():
    """get_or_create_session() creates a new empty session dict when called
    with an unknown session_id."""
    from app.session import get_or_create_session

    result = get_or_create_session("new-id-xyz")
    assert result["id"] == "new-id-xyz"
    assert result["turns"] == []


def test_get_or_create_returns_existing():
    """get_or_create_session() returns the existing session (same turns list
    reference) when called with a known session_id."""
    from app.session import append_turn, get_or_create_session

    # First call — creates the session
    get_or_create_session("same-id")

    # Mutate via append_turn between calls
    append_turn("same-id", "user", "hello")

    # Second call — must return the same live list, not a copy
    result = get_or_create_session("same-id")
    assert len(result["turns"]) == 1
    assert result["turns"][0] == {"role": "user", "content": "hello"}


def test_sliding_window_drops_oldest_pair():
    """Sliding window drops the oldest turn pair (2 messages) when
    len(turns) exceeds MAX_MESSAGES (20)."""
    from app.session import MAX_MESSAGES, append_turn, get_or_create_session

    sid = "window-test-id"
    get_or_create_session(sid)

    # Append MAX_MESSAGES + 2 turns alternating user/assistant
    roles = ["user", "assistant"]
    for i in range(MAX_MESSAGES + 2):
        append_turn(sid, roles[i % 2], f"message {i}")

    session = get_or_create_session(sid)
    assert len(session["turns"]) == MAX_MESSAGES, (
        f"expected {MAX_MESSAGES} turns after sliding window, "
        f"got {len(session['turns'])}"
    )
