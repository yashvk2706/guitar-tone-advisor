"""Tests for app/ingest/writer.py — content-hash dedup + ingest_runs lifecycle.

All DB-touching tests are gated on a live Postgres connection (DATABASE_URL set
and reachable). When the connection cannot be opened (no Postgres available in
the execution environment) the entire suite is skipped at collection time so a
CI without infrastructure stays green — the same convention used in
tests/test_schema.py.

The "no f-string SQL" test (test 12) is the only test that does NOT require a
DB and always runs.
"""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from pathlib import Path

import pytest

from app.ingest.chunker import Chunk
from app.ingest.loader import RawDocument

# ---------------------------------------------------------------------------
# DB-touching tests are gated behind a fixture that opens a real connection.
# If get_conn() fails (no Postgres available) the fixture issues pytest.skip
# so the suite is reported skipped, not failed.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_conn():
    """Open a live Postgres connection + bootstrap the schema for this module.

    Skips the entire module if Postgres is not reachable, matching the
    convention used in tests/test_schema.py so CI without infra stays green.
    """

    try:
        from app.db import get_conn, init_schema
    except Exception as e:  # pragma: no cover — import-time skip
        pytest.skip(f"app.db import failed: {e!r}")

    try:
        conn = get_conn()
    except Exception as e:  # pragma: no cover — no Postgres in env
        pytest.skip(f"Postgres not reachable: {e!r}")

    try:
        init_schema(conn)
    except Exception as e:  # pragma: no cover — schema bootstrap failed
        conn.close()
        pytest.skip(f"init_schema failed: {e!r}")

    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _clean_tables(request):
    """TRUNCATE chunks, documents, ingest_runs between tests so order is irrelevant.

    Only runs cleanup if the test requested the db_conn fixture (i.e. needs the
    DB). Static / no-DB tests are left untouched. Using request.getfixturevalue
    rather than a direct parameter so that the autouse fixture does NOT pull in
    db_conn for tests that never requested it — which would cause db_conn's
    skip-when-no-Postgres to cascade to static tests that have no DB dependency.
    """

    if "db_conn" not in request.fixturenames:
        yield
        return

    conn = request.getfixturevalue("db_conn")
    # Pre-test clean: guarantee a known empty starting state.
    with conn.cursor() as cur:
        cur.execute("TRUNCATE chunks, documents, ingest_runs CASCADE")
    conn.commit()
    yield


# ---------------------------------------------------------------------------
# Test fixtures: small in-memory RawDocument + Chunk factories.
# ---------------------------------------------------------------------------


def _make_raw_doc(
    source_id: str = "bb_king_tone.txt",
    content_hash: str = "a" * 64,
    text: str = "BB King played a Lab Series L5.",
) -> RawDocument:
    return RawDocument(
        source_type="forum",
        source_id=source_id,
        title="Bb King Tone",
        text=text,
        content_hash=content_hash,
    )


def _make_chunk(chunk_index: int, text: str = "chunk text", content_hash: str | None = None) -> Chunk:
    return Chunk(
        chunk_index=chunk_index,
        text=text,
        token_count=len(text.split()),
        content_hash=content_hash or ("c" * 63 + str(chunk_index % 10)),
        metadata={"source_filename": "bb_king_tone.txt"},
    )


def _fake_vector() -> list[float]:
    """Deterministic 1536-d test vector. NOT a real embedding — exercises the
    pgvector binding only."""

    return [0.001 * i for i in range(1536)]


# ---------------------------------------------------------------------------
# Test 1: upsert_document inserts a new row.
# ---------------------------------------------------------------------------


def test_upsert_document_inserts_new(db_conn):
    from app.ingest.writer import upsert_document

    raw = _make_raw_doc()
    doc_id = upsert_document(db_conn, raw)

    assert isinstance(doc_id, str)
    # UUID parseable
    uuid.UUID(doc_id)

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT source_type, source_id, content_hash FROM documents WHERE id = %s",
            (doc_id,),
        )
        row = cur.fetchone()
    assert row == ("forum", raw.source_id, raw.content_hash)


# ---------------------------------------------------------------------------
# Test 2: upsert_document is idempotent on same hash.
# ---------------------------------------------------------------------------


def test_upsert_document_is_idempotent_on_same_hash(db_conn):
    from app.ingest.writer import upsert_document

    raw = _make_raw_doc()
    first_id = upsert_document(db_conn, raw)
    db_conn.commit()

    with db_conn.cursor() as cur:
        cur.execute("SELECT fetched_at FROM documents WHERE id = %s", (first_id,))
        first_fetched_at = cur.fetchone()[0]

    second_id = upsert_document(db_conn, raw)
    db_conn.commit()

    with db_conn.cursor() as cur:
        cur.execute("SELECT fetched_at FROM documents WHERE id = %s", (second_id,))
        second_fetched_at = cur.fetchone()[0]

    assert first_id == second_id
    assert first_fetched_at == second_fetched_at, (
        "fetched_at must NOT change when content_hash is unchanged"
    )


# ---------------------------------------------------------------------------
# Test 3: upsert_document updates on hash change.
# ---------------------------------------------------------------------------


def test_upsert_document_updates_on_hash_change(db_conn):
    from app.ingest.writer import upsert_document

    raw_v1 = _make_raw_doc(content_hash="a" * 64)
    raw_v2 = _make_raw_doc(content_hash="b" * 64)

    doc_id = upsert_document(db_conn, raw_v1)
    db_conn.commit()
    with db_conn.cursor() as cur:
        cur.execute("SELECT fetched_at FROM documents WHERE id = %s", (doc_id,))
        first_fetched_at = cur.fetchone()[0]

    second_id = upsert_document(db_conn, raw_v2)
    db_conn.commit()

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT content_hash, fetched_at FROM documents WHERE id = %s",
            (second_id,),
        )
        new_hash, new_fetched_at = cur.fetchone()

    assert second_id == doc_id, "UUID must be preserved on update"
    assert new_hash == "b" * 64
    assert new_fetched_at > first_fetched_at


# ---------------------------------------------------------------------------
# Test 4: chunks_to_embed first-run partitions all to_embed.
# ---------------------------------------------------------------------------


def test_chunks_to_embed_first_run_partitions_all_to_embed(db_conn):
    from app.ingest.writer import chunks_to_embed, upsert_document

    raw = _make_raw_doc()
    doc_id = upsert_document(db_conn, raw)
    db_conn.commit()

    chunks = [_make_chunk(0), _make_chunk(1), _make_chunk(2)]
    to_embed, to_skip = chunks_to_embed(
        db_conn, doc_id, chunks, embedding_model="text-embedding-3-small"
    )

    assert len(to_embed) == 3
    assert len(to_skip) == 0
    assert [c.chunk_index for c in to_embed] == [0, 1, 2]


# ---------------------------------------------------------------------------
# Test 5: chunks_to_embed skips identical chunks on re-run.
# ---------------------------------------------------------------------------


def test_chunks_to_embed_unchanged_skips_all(db_conn):
    from app.ingest.writer import chunks_to_embed, upsert_chunks, upsert_document

    raw = _make_raw_doc()
    doc_id = upsert_document(db_conn, raw)
    chunks = [_make_chunk(0), _make_chunk(1)]
    vectors = [_fake_vector(), _fake_vector()]
    upsert_chunks(db_conn, doc_id, chunks, vectors, "text-embedding-3-small", source_type="forum")
    db_conn.commit()

    to_embed, to_skip = chunks_to_embed(
        db_conn, doc_id, chunks, embedding_model="text-embedding-3-small"
    )

    assert to_embed == []
    assert len(to_skip) == 2


# ---------------------------------------------------------------------------
# Test 6: chunks_to_embed re-embeds when content_hash changes.
# ---------------------------------------------------------------------------


def test_chunks_to_embed_changed_hash_re_embeds(db_conn):
    from app.ingest.writer import chunks_to_embed, upsert_chunks, upsert_document

    raw = _make_raw_doc()
    doc_id = upsert_document(db_conn, raw)
    chunks_v1 = [_make_chunk(0, content_hash="h" * 64), _make_chunk(1, content_hash="i" * 64)]
    vectors = [_fake_vector(), _fake_vector()]
    upsert_chunks(db_conn, doc_id, chunks_v1, vectors, "text-embedding-3-small", source_type="forum")
    db_conn.commit()

    # Only chunk 0's hash changed.
    chunks_v2 = [
        _make_chunk(0, content_hash="X" * 64),
        _make_chunk(1, content_hash="i" * 64),
    ]
    to_embed, to_skip = chunks_to_embed(
        db_conn, doc_id, chunks_v2, embedding_model="text-embedding-3-small"
    )

    assert len(to_embed) == 1
    assert to_embed[0].chunk_index == 0
    assert len(to_skip) == 1
    assert to_skip[0].chunk_index == 1


# ---------------------------------------------------------------------------
# Test 7: upsert_chunks writes vector(1536) — round-trip preserves first entry.
# ---------------------------------------------------------------------------


def test_upsert_chunks_inserts_with_vector(db_conn):
    from app.ingest.writer import upsert_chunks, upsert_document

    raw = _make_raw_doc()
    doc_id = upsert_document(db_conn, raw)
    chunks = [_make_chunk(0)]
    vec = _fake_vector()
    upsert_chunks(db_conn, doc_id, chunks, [vec], "text-embedding-3-small", source_type="forum")
    db_conn.commit()

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT embedding FROM chunks WHERE document_id = %s AND chunk_index = %s",
            (doc_id, 0),
        )
        row = cur.fetchone()

    assert row is not None
    stored = list(row[0])
    assert len(stored) == 1536
    assert abs(stored[0] - vec[0]) < 1e-6
    # Spot-check tail too.
    assert abs(stored[-1] - vec[-1]) < 1e-3


# ---------------------------------------------------------------------------
# Test 8: ON CONFLICT updates chunk on content_hash change.
# ---------------------------------------------------------------------------


def test_upsert_chunks_uses_on_conflict_update(db_conn):
    from app.ingest.writer import upsert_chunks, upsert_document

    raw = _make_raw_doc()
    doc_id = upsert_document(db_conn, raw)

    chunk_v1 = _make_chunk(0, text="old text", content_hash="h" * 64)
    chunk_v2 = _make_chunk(0, text="new text", content_hash="X" * 64)
    vec_v1 = _fake_vector()
    vec_v2 = [0.5] * 1536

    upsert_chunks(db_conn, doc_id, [chunk_v1], [vec_v1], "text-embedding-3-small", source_type="forum")
    db_conn.commit()
    upsert_chunks(db_conn, doc_id, [chunk_v2], [vec_v2], "text-embedding-3-small", source_type="forum")
    db_conn.commit()

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT chunk_text, content_hash, embedding FROM chunks "
            "WHERE document_id = %s AND chunk_index = %s",
            (doc_id, 0),
        )
        text, content_hash, embedding = cur.fetchone()

    assert text == "new text"
    assert content_hash == "X" * 64
    stored = list(embedding)
    assert abs(stored[0] - 0.5) < 1e-6


# ---------------------------------------------------------------------------
# Test 9: ingest_runs lifecycle — running → completed.
# ---------------------------------------------------------------------------


def test_run_lifecycle_running_to_completed(db_conn):
    from app.ingest.writer import complete_run, start_run

    run_id = start_run(db_conn, "text-embedding-3-small", full_rebuild=False)
    db_conn.commit()
    uuid.UUID(run_id)

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT status, finished_at, full_rebuild FROM ingest_runs WHERE id = %s",
            (run_id,),
        )
        status, finished_at, full_rebuild = cur.fetchone()
    assert status == "running"
    assert finished_at is None
    assert full_rebuild is False

    complete_run(
        db_conn,
        run_id=run_id,
        n_documents=10,
        n_chunks_inserted=21,
        n_chunks_skipped=0,
    )
    db_conn.commit()

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT status, finished_at, n_documents, n_chunks_inserted, n_chunks_skipped "
            "FROM ingest_runs WHERE id = %s",
            (run_id,),
        )
        status, finished_at, n_docs, n_ins, n_skip = cur.fetchone()
    assert status == "completed"
    assert finished_at is not None
    assert n_docs == 10
    assert n_ins == 21
    assert n_skip == 0


# ---------------------------------------------------------------------------
# Test 10: ingest_runs lifecycle — running → failed.
# ---------------------------------------------------------------------------


def test_run_lifecycle_fail(db_conn):
    from app.ingest.writer import fail_run, start_run

    run_id = start_run(db_conn, "text-embedding-3-small", full_rebuild=False)
    db_conn.commit()

    fail_run(db_conn, run_id, error="RuntimeError('simulated')")
    db_conn.commit()

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT status, finished_at, error FROM ingest_runs WHERE id = %s",
            (run_id,),
        )
        status, finished_at, error = cur.fetchone()

    assert status == "failed"
    assert finished_at is not None
    assert "simulated" in error


# ---------------------------------------------------------------------------
# Test 11: truncate_all empties chunks + documents.
# ---------------------------------------------------------------------------


def test_truncate_all(db_conn):
    from app.ingest.writer import truncate_all, upsert_chunks, upsert_document

    raw = _make_raw_doc()
    doc_id = upsert_document(db_conn, raw)
    upsert_chunks(
        db_conn,
        doc_id,
        [_make_chunk(0)],
        [_fake_vector()],
        "text-embedding-3-small",
        source_type="forum",
    )
    db_conn.commit()

    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks")
        assert cur.fetchone()[0] >= 1
        cur.execute("SELECT COUNT(*) FROM documents")
        assert cur.fetchone()[0] >= 1

    truncate_all(db_conn)
    db_conn.commit()

    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM documents")
        assert cur.fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Test 12: No f-string SQL in writer.py. Runs without a DB.
# ---------------------------------------------------------------------------


def test_no_fstring_sql_in_writer():
    """T-04-01 mitigation: every SQL statement must use %s placeholders.

    Scans app/ingest/writer.py for any occurrence of f"...{...}...SELECT..." /
    INSERT / UPDATE / DELETE / TRUNCATE. The regex is deliberately liberal
    (matches f-strings containing a SQL keyword) so that even a clever
    obfuscation surfaces. This is enforced by a grep, not by AST: grep is
    cheap and the failure mode (a tampering vector hidden in a comment)
    would require the offender to disable this test, which is itself a red
    flag in code review.
    """

    writer_path = (
        Path(__file__).resolve().parent.parent / "app" / "ingest" / "writer.py"
    )
    assert writer_path.exists(), f"writer.py missing at {writer_path}"
    contents = writer_path.read_text(encoding="utf-8")

    # Match: f"..." or f'...' that contains a SQL DML/DDL keyword and a brace.
    pattern = re.compile(
        r"""f["'][^"']*\{[^"']*(SELECT|INSERT|UPDATE|DELETE|TRUNCATE)[^"']*["']""",
        re.IGNORECASE,
    )
    offenders = [line for line in contents.splitlines() if pattern.search(line)]
    assert offenders == [], (
        f"f-string SQL detected in writer.py (T-04-01 violation):\n  "
        + "\n  ".join(offenders)
    )

    # Cross-check via grep as a defensive secondary signal (matches the
    # acceptance-criteria gate exactly).
    try:
        proc = subprocess.run(
            [
                "grep",
                "-E",
                r"f['\"](SELECT|INSERT|UPDATE|DELETE|TRUNCATE)",
                str(writer_path),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # grep returns 1 when no matches (expected); 0 when a match exists.
        if proc.returncode == 0:
            non_comment = [
                ln for ln in proc.stdout.splitlines() if not ln.lstrip().startswith("#")
            ]
            assert non_comment == [], (
                "grep found f-string SQL: " + "\n".join(non_comment)
            )
    except FileNotFoundError:  # pragma: no cover — no grep on PATH
        pass


# ---------------------------------------------------------------------------
# Test 13: _PHASE_1_SOURCE_TYPE constant is gone. Runs without a DB.
# ---------------------------------------------------------------------------


def test_upsert_chunks_source_type_not_hardcoded():
    """Verify that the _PHASE_1_SOURCE_TYPE hardcode has been removed from writer.py.

    This is a static scan — no Postgres required. The test asserts that the
    string ``_PHASE_1_SOURCE_TYPE`` does not appear anywhere in the file,
    confirming the Phase 6 writer fix is in place.
    """

    writer_path = (
        Path(__file__).resolve().parent.parent / "app" / "ingest" / "writer.py"
    )
    assert writer_path.exists(), f"writer.py missing at {writer_path}"
    contents = writer_path.read_text(encoding="utf-8")

    assert "_PHASE_1_SOURCE_TYPE" not in contents, (
        "writer.py still contains _PHASE_1_SOURCE_TYPE — the Phase 6 writer "
        "fix has not been applied. upsert_chunks() must accept source_type as "
        "a required parameter and use it directly instead of the hardcoded constant."
    )


# ---------------------------------------------------------------------------
# Test 14: upsert_chunks stores the correct source_type (DB-gated).
# ---------------------------------------------------------------------------


def test_upsert_chunks_uses_source_type(db_conn):
    """Verify that upsert_chunks writes the caller-supplied source_type to the DB.

    Inserts a chunk with source_type="pdf_manual" and reads it back from the
    chunks table. The stored value must equal "pdf_manual", not "forum".

    This is the key regression test for the Phase 6 writer bug fix.
    """

    from app.ingest.writer import upsert_chunks, upsert_document

    # Create a document with source_type="pdf_manual".
    raw = RawDocument(
        source_type="pdf_manual",
        source_id="fender_twin_reverb.pdf",
        title="Fender Twin Reverb",
        text="Fender Twin Reverb manual content.",
        content_hash="p" * 64,
    )
    doc_id = upsert_document(db_conn, raw)

    # Write a chunk with source_type="pdf_manual".
    upsert_chunks(
        db_conn,
        doc_id,
        [_make_chunk(0)],
        [_fake_vector()],
        "text-embedding-3-small",
        source_type="pdf_manual",
    )
    db_conn.commit()

    # Read back the stored source_type.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT source_type FROM chunks WHERE document_id = %s AND chunk_index = 0",
            (doc_id,),
        )
        row = cur.fetchone()

    assert row is not None, "No chunk row found after upsert_chunks"
    assert row[0] == "pdf_manual", (
        f"Expected source_type='pdf_manual', got {row[0]!r}. "
        "upsert_chunks() is still using a hardcoded source_type instead of "
        "the caller-supplied value."
    )
