"""FastAPI endpoint tests — Phase 3. 2 offline tests + 1 live-DB integration (skipped if Postgres
unreachable). Uses starlette TestClient (no pytest-asyncio needed)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# DB-gated fixture (copied verbatim from tests/test_retrieval.py lines 44-61)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_conn():
    """Live Postgres connection + schema bootstrap. Skip if unreachable."""
    try:
        from app.db import get_conn, init_schema
    except Exception as e:
        pytest.skip(f"app.db import failed: {e!r}")
    try:
        conn = get_conn()
    except Exception as e:
        pytest.skip(f"Postgres not reachable: {e!r}")
    try:
        init_schema(conn)
    except Exception as e:
        conn.close()
        pytest.skip(f"init_schema failed: {e!r}")
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# autouse fixture — clears session state between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_sessions():
    """Clear app.session._sessions before and after each test."""
    try:
        import app.session as s

        s._sessions.clear()
    except (ImportError, AttributeError):
        pass
    yield
    try:
        import app.session as s

        s._sessions.clear()
    except (ImportError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# Test 1 (03-02-01): POST /chat returns 200 with Content-Type: text/event-stream
# ---------------------------------------------------------------------------


def test_chat_endpoint_returns_event_stream(monkeypatch):
    """POST /chat must return HTTP 200 with Content-Type containing text/event-stream.

    Uses monkeypatch to replace retrieve() and stream_response() with fakes so
    this test runs offline without Anthropic API or Postgres.
    """
    # Import app lazily — fails gracefully if app/main.py doesn't exist yet
    try:
        import app.main as main_module
        from app.main import app
    except (ImportError, ModuleNotFoundError) as e:
        pytest.fail(f"app/main.py not importable: {e!r}")

    from starlette.testclient import TestClient

    # Fake retrieve() — returns empty sources list
    monkeypatch.setattr(main_module, "retrieve", lambda query, k=8: [])

    # Fake stream_response — async generator yielding minimal SSE events
    from sse_starlette.event import ServerSentEvent

    async def _fake_stream_response(
        *,
        client,
        system_blocks,
        messages,
        sources,
        session_id,
    ):
        yield ServerSentEvent(
            data=json.dumps({"session_id": session_id}),
            event="session",
        )
        yield ServerSentEvent(
            data=json.dumps({"sources": []}),
            event="citations",
        )

    monkeypatch.setattr(main_module, "stream_response", _fake_stream_response)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/chat",
            json={"session_id": None, "message": "Strat clean tone", "gear": None},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "text/event-stream" in resp.headers.get("content-type", ""), (
        f"Expected text/event-stream in Content-Type, got {resp.headers.get('content-type')!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 (03-02-02): GET /sources/{chunk_id} returns chunk_text (live-DB gated)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_source_returns_chunk_text(db_conn):
    """GET /sources/{chunk_id} must return chunk_text for a known chunk_id.

    Requires live Postgres. Skipped gracefully if Postgres is unreachable.
    Inserts a minimal document + chunk row, calls the endpoint, verifies response.
    """
    try:
        from app.main import app
    except (ImportError, ModuleNotFoundError) as e:
        pytest.skip(f"app/main.py not importable: {e!r}")

    from starlette.testclient import TestClient

    # Insert a minimal document row
    insert_doc_sql = """
        INSERT INTO documents (source_type, source_id, title, content_hash, metadata_json)
        VALUES ('forum', 'test_source_check', 'Test Doc', 'deadbeef_test', '{}')
        ON CONFLICT (source_type, source_id) DO UPDATE SET title = EXCLUDED.title
        RETURNING id::text
    """
    with db_conn.cursor() as cur:
        cur.execute(insert_doc_sql)
        doc_id = cur.fetchone()[0]

    # Insert a minimal chunk row
    insert_chunk_sql = """
        INSERT INTO chunks (
            document_id, source_type, chunk_index, chunk_text, content_hash,
            token_count, embedding_model, embedding, metadata_json
        ) VALUES (
            %s::uuid, 'forum', 0, 'This is test chunk text for endpoint test.',
            'chunkhash_endpoint_test', 10, 'text-embedding-3-small',
            array_fill(0, ARRAY[1536])::vector, '{"source_filename": "test_source.txt"}'
        )
        ON CONFLICT (document_id, chunk_index, embedding_model) DO UPDATE
            SET chunk_text = EXCLUDED.chunk_text
        RETURNING id::text
    """
    with db_conn.cursor() as cur:
        cur.execute(insert_chunk_sql, (doc_id,))
        chunk_id = cur.fetchone()[0]

    db_conn.commit()

    with TestClient(app) as client:
        resp = client.get(f"/sources/{chunk_id}")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "chunk_text" in body, f"'chunk_text' key missing from response: {body}"
    assert body["chunk_text"] == "This is test chunk text for endpoint test."


# ---------------------------------------------------------------------------
# Test 3 (03-02-03): No f-string SQL in app/main.py
# ---------------------------------------------------------------------------


def test_no_fstring_sql_in_main():
    """No f-string SQL in app/main.py (CLAUDE.md constraint T-03-07).

    Same regex as test_retrieval.py::test_no_fstring_sql_in_base but scans app/main.py.
    """
    main_path = Path(__file__).resolve().parent.parent / "app" / "main.py"
    assert main_path.exists(), "app/main.py not found"
    contents = main_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"""f["'][^"']*\{[^"']*(SELECT|INSERT|UPDATE|DELETE|TRUNCATE)[^"']*["']""",
        re.IGNORECASE,
    )
    offenders = [line for line in contents.splitlines() if pattern.search(line)]
    assert offenders == [], f"f-string SQL found in app/main.py: {offenders}"
