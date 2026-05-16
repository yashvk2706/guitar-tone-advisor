"""Smoke tests for the Phase 1 Postgres + pgvector schema.

These tests require a live local Postgres reachable via ``DATABASE_URL`` with
``CREATE EXTENSION`` privileges. Run after ``psql -f scripts/init_db.sql``.

Six checks (per 01-01-PLAN.md):
    1. ``vector`` and ``pg_trgm`` extensions installed.
    2. ``documents``, ``chunks``, ``ingest_runs`` tables present with the
       documented columns.
    3. ``chunks_embedding_hnsw_cos`` HNSW index exists on
       ``chunks.embedding`` with ``vector_cosine_ops``, ``m=16``,
       ``ef_construction=64``.
    4. UNIQUE ``(document_id, chunk_index, embedding_model)`` on ``chunks``.
    5. ``scripts/init_db.sql`` is idempotent — running it twice raises nothing.
    6. ``get_conn()`` already registered pgvector — inserting a 1536-d literal
       into a temp table succeeds.

All queries use ``%s`` parameter binding; SQL is never f-stringed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db import get_conn, init_schema

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INIT_SQL_PATH = PROJECT_ROOT / "scripts" / "init_db.sql"


@pytest.fixture(scope="module")
def conn():
    """One module-scoped connection; schema initialised once."""

    connection = get_conn()
    init_schema(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_extensions_installed(conn) -> None:
    """vector and pg_trgm extensions must be installed."""

    with conn.cursor() as cur:
        cur.execute(
            "SELECT extname FROM pg_extension WHERE extname IN (%s, %s) ORDER BY extname",
            ("pg_trgm", "vector"),
        )
        names = [row[0] for row in cur.fetchall()]
    assert names == ["pg_trgm", "vector"], f"expected both extensions, got {names!r}"


def test_tables_exist(conn) -> None:
    """documents, chunks, ingest_runs exist with the documented columns."""

    expected = {
        "documents": {
            "id",
            "source_type",
            "source_id",
            "title",
            "fetched_at",
            "content_hash",
            "metadata_json",
        },
        "chunks": {
            "id",
            "document_id",
            "source_type",
            "chunk_index",
            "chunk_text",
            "content_hash",
            "token_count",
            "embedding_model",
            "embedding",
            "metadata_json",
            "created_at",
        },
        "ingest_runs": {
            "id",
            "started_at",
            "finished_at",
            "embedding_model",
            "n_documents",
            "n_chunks_inserted",
            "n_chunks_skipped",
            "status",
            "error",
            "full_rebuild",
        },
    }

    with conn.cursor() as cur:
        for table, expected_cols in expected.items():
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s",
                (table,),
            )
            actual_cols = {row[0] for row in cur.fetchall()}
            assert actual_cols, f"table {table!r} not found"
            missing = expected_cols - actual_cols
            assert not missing, f"table {table!r} missing columns: {missing!r}"


def test_hnsw_index_present(conn) -> None:
    """chunks_embedding_hnsw_cos must use hnsw + vector_cosine_ops + m=16 + ef_construction=64."""

    with conn.cursor() as cur:
        cur.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s",
            ("chunks_embedding_hnsw_cos",),
        )
        row = cur.fetchone()
    assert row is not None, "chunks_embedding_hnsw_cos index not found"
    indexdef = row[0].lower()
    assert "hnsw" in indexdef, f"index is not HNSW: {indexdef!r}"
    assert "vector_cosine_ops" in indexdef, f"index missing vector_cosine_ops: {indexdef!r}"
    # Postgres normalises whitespace around `=` so check both styles.
    assert "m='16'" in indexdef or "m=16" in indexdef or "m = 16" in indexdef, (
        f"index missing m=16: {indexdef!r}"
    )
    assert (
        "ef_construction='64'" in indexdef
        or "ef_construction=64" in indexdef
        or "ef_construction = 64" in indexdef
    ), f"index missing ef_construction=64: {indexdef!r}"


def test_unique_constraint_on_chunks(conn) -> None:
    """UNIQUE (document_id, chunk_index, embedding_model) must exist on chunks."""

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'chunks' AND c.contype = 'u'
            """
        )
        unique_constraints = [row[0] for row in cur.fetchall()]
        assert unique_constraints, "no unique constraints found on chunks"

        # For each unique constraint, fetch the column list and check the trio.
        found_trio = False
        for conname in unique_constraints:
            cur.execute(
                """
                SELECT a.attname
                FROM pg_constraint c
                JOIN pg_class t  ON t.oid = c.conrelid
                JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
                WHERE c.conname = %s AND t.relname = 'chunks'
                ORDER BY k.ord
                """,
                (conname,),
            )
            cols = [row[0] for row in cur.fetchall()]
            if cols == ["document_id", "chunk_index", "embedding_model"]:
                found_trio = True
                break
        assert found_trio, (
            "no UNIQUE (document_id, chunk_index, embedding_model) constraint found; "
            f"got constraints {unique_constraints!r}"
        )


def test_init_db_is_idempotent(conn) -> None:
    """Re-running scripts/init_db.sql against an already-initialised DB is a no-op."""

    ddl = INIT_SQL_PATH.read_text(encoding="utf-8")
    # `init_schema(conn)` already ran once via the fixture; do it a second time.
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()


def test_register_vector_active(conn) -> None:
    """After get_conn(), inserting a 1536-d vector literal must succeed.

    We use a TEMP TABLE so we don't pollute the real chunks table. The
    pgvector adapter (registered inside get_conn) translates a Python list of
    floats into the ``vector`` type via psycopg's adapters.
    """

    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE _vec_smoke (v vector(1536)) ON COMMIT DROP")
        vec = [0.001] * 1536
        cur.execute("INSERT INTO _vec_smoke (v) VALUES (%s)", (vec,))
        cur.execute("SELECT vector_dims(v) FROM _vec_smoke")
        dims = cur.fetchone()[0]
        assert dims == 1536, f"expected 1536 dims, got {dims}"
    conn.rollback()
