"""In-process session memory for per-session conversation history.

Design decisions (from CONTEXT.md):
    D-10: In-process Python dict keyed by ``session_id`` (UUID string). No Redis,
          no DB storage. Server restart clears all sessions — acceptable for a
          personal single-user local tool.
    D-11: Gear context lives in the first user message as a ``<gear>`` block.
          The system prompt stays stable across all turns for prompt caching.
    D-12: Sliding window — retain the last ``MAX_MESSAGES`` messages (10 turn
          pairs). When history exceeds the budget, drop the oldest turn pair
          (always 2 messages) to preserve role alternation. No summarization.

Source ID stability:
    Each session tracks a ``source_map`` (chunk_id → assigned S-number) and a
    monotonically incrementing ``source_counter``. Calling ``register_sources()``
    for each turn's retrieved chunks assigns stable, session-global S-numbers:
    the same chunk always gets the same S{n} within a session, and new chunks
    receive the next available number. This prevents [S3] in one turn from
    referring to a different chunk than [S3] in the next turn.

Thread safety:
    ``_lock`` (threading.Lock) guards all reads and writes to ``_sessions``.
    FastAPI + uvicorn (single-process async) means true concurrent session
    writes are uncommon, but the lock adds no measurable overhead and prevents
    data corruption in multi-tab or multi-request scenarios.

Test isolation:
    Tests reset state between runs via::

        import app.session as s
        s._sessions.clear()

    This is the autouse fixture pattern from ``tests/test_session.py``.
"""

from __future__ import annotations

import threading

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_sessions: dict[str, dict] = {}
# Each value: {"turns": list[dict], "source_map": dict[str, int], "source_counter": int}

_lock = threading.Lock()

MAX_MESSAGES: int = 20  # 10 turn pairs (D-12: retain last 10–15 pairs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_or_create_session(session_id: str) -> dict:
    """Return the session dict for ``session_id``, creating it if absent.

    The returned dict is ``{"id": session_id, "turns": <live list>}``.
    The ``turns`` list is the *same object* stored in ``_sessions`` — callers
    that append via ``append_turn()`` will see the change without re-fetching.

    Args:
        session_id: Opaque UUID string from the client. Treated as a key only;
                    no validation performed (single-user local tool — T-03-04).

    Returns:
        ``{"id": session_id, "turns": list[dict]}`` where ``turns`` is the live
        mutable list for this session (empty list for new sessions).
    """
    with _lock:
        if session_id not in _sessions:
            _sessions[session_id] = {
                "turns": [],
                "source_map": {},
                "source_counter": 0,
            }
        return {"id": session_id, "turns": _sessions[session_id]["turns"]}


def append_turn(session_id: str, role: str, content: str) -> None:
    """Append one turn to ``session_id``'s history and apply the sliding window.

    Creates the session if it does not yet exist (same as calling
    ``get_or_create_session`` followed by a manual append).

    Sliding-window invariant: after each call, ``len(turns) <= MAX_MESSAGES``.
    When the window is full, ``del turns[:2]`` drops the two oldest messages
    (one user turn + one assistant turn). Dropping exactly 2 preserves role
    alternation (D-12) — never drop a lone user message without its paired
    assistant response.

    Args:
        session_id: UUID key for the session (created if absent).
        role:       ``"user"`` or ``"assistant"`` — follows the Anthropic
                    messages API convention.
        content:    Full message text for this turn.
    """
    with _lock:
        session = _sessions.setdefault(
            session_id,
            {"turns": [], "source_map": {}, "source_counter": 0},
        )
        turns = session["turns"]
        turns.append({"role": role, "content": content})
        # Sliding window: drop oldest pair until within budget (preserves role
        # alternation — always drops 2 at a time). Using while instead of if
        # ensures the window converges to exactly MAX_MESSAGES regardless of
        # how many turns were appended in a single call.
        while len(turns) > MAX_MESSAGES:
            del turns[:2]


def register_sources(session_id: str, chunk_ids: list[str]) -> list[int]:
    """Assign stable session-global S-numbers to a list of chunk IDs.

    Each unique chunk_id is assigned a monotonically increasing integer once
    per session and reused on subsequent turns. This ensures that [S3] always
    refers to the same chunk within a session, regardless of retrieval order.

    Args:
        session_id: UUID key for the session (created if absent).
        chunk_ids:  Ordered list of chunk IDs from the current turn's retrieval.

    Returns:
        List of assigned S-numbers in the same order as ``chunk_ids``.
        E.g. for a session where S1 and S2 were assigned in turn 1, a new
        chunk in turn 2 gets S3, while a repeated chunk keeps its prior number.
    """
    with _lock:
        session = _sessions.setdefault(
            session_id,
            {"turns": [], "source_map": {}, "source_counter": 0},
        )
        source_map = session["source_map"]
        assigned: list[int] = []
        for chunk_id in chunk_ids:
            if chunk_id not in source_map:
                session["source_counter"] += 1
                source_map[chunk_id] = session["source_counter"]
            assigned.append(source_map[chunk_id])
        return assigned
