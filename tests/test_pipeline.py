"""End-to-end smoke tests for the ingestion pipeline CLI.

Tests 1-4 require BOTH:
    - DATABASE_URL pointing at a Postgres reachable from this environment
    - OPENAI_API_KEY set (real, for actually hitting the embeddings endpoint)
and are gated behind a fixture that calls pytest.skip when either is missing.

Tests 5-6 (`test_uses_only_embedder_protocol`, `test_help_works`) are static /
infra-free and always run — they protect the Embedder-Protocol hard
constraint and the argparse wiring respectively.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

from app.embeddings.base import EmbeddingResult


# ---------------------------------------------------------------------------
# Live-infra gate
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_conn():
    """Live Postgres connection + bootstrap schema. Skip if unreachable."""

    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set — skipping live-pipeline tests")

    try:
        from app.db import get_conn, init_schema
    except Exception as e:  # pragma: no cover
        pytest.skip(f"app.db import failed: {e!r}")

    try:
        conn = get_conn()
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Postgres not reachable: {e!r}")

    try:
        init_schema(conn)
    except Exception as e:  # pragma: no cover
        conn.close()
        pytest.skip(f"init_schema failed: {e!r}")

    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _clean_tables_for_db_tests(request):
    """TRUNCATE all tables before each DB-using test so prior state is wiped."""

    if "db_conn" not in request.fixturenames:
        yield
        return

    db_conn = request.getfixturevalue("db_conn")
    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE chunks, documents, ingest_runs CASCADE")
    db_conn.commit()
    yield


# ---------------------------------------------------------------------------
# Test 1: First run populates chunks.
# ---------------------------------------------------------------------------


def test_first_run_populates_chunks(db_conn):
    from app.ingest.pipeline import main

    rc = main([])
    assert rc == 0

    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks")
        n_chunks = cur.fetchone()[0]
        cur.execute("SELECT DISTINCT embedding_model FROM chunks")
        models = {row[0] for row in cur.fetchall()}
        cur.execute(
            "SELECT n_documents, n_chunks_inserted, n_chunks_skipped, status "
            "FROM ingest_runs ORDER BY started_at DESC LIMIT 1"
        )
        n_docs, n_ins, n_skip, status = cur.fetchone()

    assert n_chunks > 0
    assert len(models) == 1, f"all chunks must share an embedding_model, got {models}"
    assert n_docs == 10, "Phase 1 corpus has exactly 10 forum files"
    assert n_ins == n_chunks
    assert n_skip == 0
    assert status == "completed"


# ---------------------------------------------------------------------------
# Test 2: Second run is idempotent (INGEST-06).
# ---------------------------------------------------------------------------


def test_second_run_is_idempotent(db_conn):
    from app.ingest.pipeline import main

    rc1 = main([])
    assert rc1 == 0

    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks")
        first_total = cur.fetchone()[0]

    t0 = time.monotonic()
    rc2 = main([])
    second_duration = time.monotonic() - t0
    assert rc2 == 0

    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks")
        second_total = cur.fetchone()[0]
        cur.execute(
            "SELECT n_chunks_inserted, n_chunks_skipped, status "
            "FROM ingest_runs ORDER BY started_at DESC LIMIT 1"
        )
        n_ins, n_skip, status = cur.fetchone()

    assert second_total == first_total
    assert n_ins == 0, "second run must re-embed zero chunks (INGEST-06)"
    assert n_skip == first_total
    assert status == "completed"
    # Soft sanity: idempotent run should be noticeably faster than the first
    # since no embedding API calls are made. We give it a generous ceiling.
    assert second_duration < 30.0


# ---------------------------------------------------------------------------
# Test 3: --full-rebuild truncates and re-embeds.
# ---------------------------------------------------------------------------


def test_full_rebuild_truncates_and_re_embeds(db_conn):
    from app.ingest.pipeline import main

    assert main([]) == 0
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks")
        first_total = cur.fetchone()[0]

    assert main(["--full-rebuild"]) == 0
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT full_rebuild, n_chunks_inserted, n_chunks_skipped "
            "FROM ingest_runs ORDER BY started_at DESC LIMIT 1"
        )
        full_rebuild, n_ins, n_skip = cur.fetchone()

    assert full_rebuild is True
    assert n_ins == first_total
    assert n_skip == 0


# ---------------------------------------------------------------------------
# Test 4: Embedding failure records a failed ingest_runs row.
# ---------------------------------------------------------------------------


def test_failure_records_failed_run(db_conn, monkeypatch):
    from app import ingest
    from app.ingest import pipeline

    class _BoomEmbedder:
        model = "text-embedding-3-small"
        dim = 1536
        provider = "openai"

        def embed_documents(self, texts):
            raise RuntimeError("simulated embedding outage")

        def embed_query(self, text):  # pragma: no cover
            raise RuntimeError("simulated embedding outage")

    monkeypatch.setattr(pipeline, "get_embedder", lambda: _BoomEmbedder())

    with pytest.raises(RuntimeError):
        pipeline.main([])

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT status, error FROM ingest_runs ORDER BY started_at DESC LIMIT 1"
        )
        status, error = cur.fetchone()
    assert status == "failed"
    assert error is not None
    assert "simulated" in error


# ---------------------------------------------------------------------------
# Test 5: Pipeline only uses the Embedder Protocol (no direct openai imports).
# ---------------------------------------------------------------------------


def test_uses_only_embedder_protocol():
    """CLAUDE.md hard constraint: nothing outside app/embeddings/openai_embedder.py
    may import the ``openai`` package directly. The pipeline must always go
    through the factory."""

    pipeline_src = Path(__file__).resolve().parent.parent / "app" / "ingest" / "pipeline.py"
    assert pipeline_src.exists()
    contents = pipeline_src.read_text(encoding="utf-8")

    # Reject "from openai" and "import openai" at any indent level. Comments
    # mentioning openai are allowed (they don't import the package).
    bad = re.compile(r"^\s*(from openai\b|import openai\b)", re.MULTILINE)
    matches = bad.findall(contents)
    assert matches == [], (
        f"app/ingest/pipeline.py must not import openai directly; found: {matches}"
    )

    # Positive signal: factory must be imported.
    assert "get_embedder" in contents, (
        "pipeline.py must use the Embedder factory (get_embedder)"
    )


# ---------------------------------------------------------------------------
# Test 6: --help works without DB or API key.
# ---------------------------------------------------------------------------


def test_help_works(capsys):
    from app.ingest.pipeline import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    # argparse exits 0 on --help.
    assert exc.value.code == 0

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "--full-rebuild" in output
    assert "--forum-dir" in output
