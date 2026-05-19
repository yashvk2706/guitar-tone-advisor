"""Retrieval layer tests — Phase 2 Plan 01.

Covers:
  - gear_aliases.json file structure (INGEST-07)
  - expand_query() bidirectional expansion (INGEST-07)
  - ChunkResult dataclass shape and immutability (RETR-03)
  - retrieve() with injected fake connection/embedder (RETR-01)
  - Static-scan guards: no f-string SQL, no direct openai import,
    register_vector not called inside retrieve() (CLAUDE.md constraints)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_alias_cache():
    """Clear lru_cache before and after every test so alias file changes are
    picked up without cross-test contamination."""
    from app.retrieval.aliases import _load_alias_pairs

    _load_alias_pairs.cache_clear()
    yield
    _load_alias_pairs.cache_clear()


# ---------------------------------------------------------------------------
# DB-gated fixture (skips gracefully if Postgres is unavailable)
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
# Fake objects for offline unit tests
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def execute(self, sql, params):
        pass

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)


class _FakeEmbedder:
    model = "text-embedding-3-small"
    dim = 1536
    provider = "openai"

    def embed_documents(self, texts):
        from app.embeddings.base import EmbeddingResult

        return EmbeddingResult(
            vectors=[[0.0] * 1536] * len(list(texts)),
            model=self.model,
            dim=self.dim,
            provider=self.provider,
        )

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 1536


# ---------------------------------------------------------------------------
# INGEST-07: alias file structure tests
# ---------------------------------------------------------------------------


def test_aliases_json_loads():
    """gear_aliases.json must exist, parse as valid JSON, and contain exactly
    14 entries each with 'shortform' and 'canonical' string fields."""
    alias_path = Path(__file__).resolve().parent.parent / "data" / "gear_aliases.json"
    assert alias_path.exists(), f"gear_aliases.json not found at {alias_path}"
    data = json.loads(alias_path.read_text(encoding="utf-8"))
    assert "aliases" in data, "top-level 'aliases' key missing"
    assert len(data["aliases"]) == 14, (
        f"expected 14 alias pairs, got {len(data['aliases'])}"
    )
    for entry in data["aliases"]:
        assert "shortform" in entry, f"missing 'shortform' in {entry}"
        assert "canonical" in entry, f"missing 'canonical' in {entry}"
        assert isinstance(entry["shortform"], str)
        assert isinstance(entry["canonical"], str)


# ---------------------------------------------------------------------------
# INGEST-07: expand_query() bidirectional expansion tests
# ---------------------------------------------------------------------------


def test_expand_shortform():
    """Shortform token in query is expanded to 'shortform canonical'."""
    from app.retrieval.aliases import expand_query

    result = expand_query("Strat neck pickup clean tone", [("Strat", "Stratocaster")])
    assert result == "Strat Stratocaster neck pickup clean tone", repr(result)


def test_expand_canonical():
    """Canonical token in query is expanded to 'shortform canonical'."""
    from app.retrieval.aliases import expand_query

    result = expand_query(
        "Stratocaster neck pickup clean tone", [("Strat", "Stratocaster")]
    )
    assert result == "Strat Stratocaster neck pickup clean tone", repr(result)


def test_expand_case_insensitive():
    """Expansion must be case-insensitive — 'strat' expands the same as 'Strat'."""
    from app.retrieval.aliases import expand_query

    result = expand_query("strat tone", [("Strat", "Stratocaster")])
    assert result == "Strat Stratocaster tone", repr(result)


def test_expand_count_one():
    """When shortform appears multiple times, only the first occurrence is
    expanded (count=1 prevents duplication)."""
    from app.retrieval.aliases import expand_query

    result = expand_query("Strat Strat tone", [("Strat", "Stratocaster")])
    assert result == "Strat Stratocaster Strat tone", repr(result)


def test_expand_no_match():
    """Query with no alias tokens is returned unchanged."""
    from app.retrieval.aliases import expand_query

    result = expand_query("no match here", [("Strat", "Stratocaster")])
    assert result == "no match here", repr(result)


def test_expand_empty_pairs():
    """expand_query with empty alias_pairs returns query unchanged."""
    from app.retrieval.aliases import expand_query

    result = expand_query("Stratocaster tone", [])
    assert result == "Stratocaster tone", repr(result)


def test_load_alias_pairs_returns_14_tuples():
    """_load_alias_pairs() returns list of 14 (shortform, canonical) tuples."""
    from app.retrieval.aliases import _load_alias_pairs

    pairs = _load_alias_pairs()
    assert len(pairs) == 14, f"expected 14 pairs, got {len(pairs)}"
    for shortform, canonical in pairs:
        assert isinstance(shortform, str)
        assert isinstance(canonical, str)


# ---------------------------------------------------------------------------
# RETR-03: ChunkResult dataclass tests
# ---------------------------------------------------------------------------


def test_chunk_result_fields():
    """ChunkResult must expose all required typed fields."""
    from app.retrieval.base import ChunkResult

    cr = ChunkResult(
        chunk_id="abc-123",
        document_id="doc-456",
        source_type="forum",
        source_name="bb_king_tone.txt",
        chunk_index=0,
        text="Some chunk text",
        distance=0.25,
    )
    assert cr.chunk_id == "abc-123"
    assert cr.document_id == "doc-456"
    assert cr.source_type == "forum"
    assert cr.source_name == "bb_king_tone.txt"
    assert cr.chunk_index == 0
    assert cr.text == "Some chunk text"
    assert cr.distance == 0.25


def test_chunk_result_is_frozen():
    """ChunkResult must be a frozen dataclass (immutable)."""
    from app.retrieval.base import ChunkResult

    cr = ChunkResult(
        chunk_id="x",
        document_id="y",
        source_type="forum",
        source_name="test.txt",
        chunk_index=0,
        text="hello",
        distance=0.1,
    )
    with pytest.raises((AttributeError, TypeError)):
        cr.chunk_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RETR-01: retrieve() offline unit tests (injected fake conn + embedder)
# ---------------------------------------------------------------------------


def _make_fake_row(
    chunk_id="id-1",
    document_id="doc-1",
    source_type="forum",
    chunk_index=0,
    chunk_text="Test chunk text.",
    metadata_json='{"source_filename": "test_tone.txt"}',
    distance=0.1,
):
    return (
        chunk_id,
        document_id,
        source_type,
        chunk_index,
        chunk_text,
        metadata_json,
        distance,
    )


def test_retrieve_fewer_than_k():
    """retrieve() returns fewer than k results when DB has fewer than k chunks."""
    from app.retrieval.base import retrieve

    rows = [_make_fake_row(chunk_id=f"id-{i}") for i in range(3)]
    results = retrieve("some tone query", k=8, conn=_FakeConn(rows), embedder=_FakeEmbedder())
    assert len(results) == 3
    from app.retrieval.base import ChunkResult

    assert all(isinstance(r, ChunkResult) for r in results)


def test_retrieve_empty_db():
    """retrieve() returns an empty list when DB has no chunks."""
    from app.retrieval.base import retrieve

    results = retrieve("any query", k=8, conn=_FakeConn([]), embedder=_FakeEmbedder())
    assert results == []


def test_retrieve_maps_source_name():
    """retrieve() populates source_name from metadata_json['source_filename']."""
    from app.retrieval.base import retrieve

    row = _make_fake_row(
        metadata_json='{"source_filename": "bb_king_tone.txt"}',
    )
    results = retrieve("bb king tone", k=1, conn=_FakeConn([row]), embedder=_FakeEmbedder())
    assert len(results) == 1
    assert results[0].source_name == "bb_king_tone.txt"


def test_retrieve_source_name_fallback():
    """retrieve() falls back to 'unknown' when source_filename missing from metadata."""
    from app.retrieval.base import retrieve

    row = _make_fake_row(metadata_json='{}')
    results = retrieve("query", k=1, conn=_FakeConn([row]), embedder=_FakeEmbedder())
    assert results[0].source_name == "unknown"


# ---------------------------------------------------------------------------
# Static scan guards
# ---------------------------------------------------------------------------


def test_no_fstring_sql_in_base():
    """No f-string SQL in app/retrieval/base.py (CLAUDE.md constraint)."""
    base_path = (
        Path(__file__).resolve().parent.parent / "app" / "retrieval" / "base.py"
    )
    assert base_path.exists(), "app/retrieval/base.py not found"
    contents = base_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"""f["'][^"']*\{[^"']*(SELECT|INSERT|UPDATE|DELETE|TRUNCATE)[^"']*["']""",
        re.IGNORECASE,
    )
    offenders = [line for line in contents.splitlines() if pattern.search(line)]
    assert offenders == [], f"f-string SQL found in base.py: {offenders}"


# Alias required by 02-02-PLAN.md verification command.
test_no_fstring_sql = test_no_fstring_sql_in_base


def test_no_direct_openai_import():
    """No direct 'import openai' or 'from openai' in app/retrieval/ (CLAUDE.md)."""
    retrieval_dir = (
        Path(__file__).resolve().parent.parent / "app" / "retrieval"
    )
    assert retrieval_dir.exists(), "app/retrieval/ directory not found"
    pattern = re.compile(r"^(from openai\b|import openai\b)", re.MULTILINE)
    violators = [
        str(f)
        for f in retrieval_dir.rglob("*.py")
        if pattern.search(f.read_text(encoding="utf-8"))
    ]
    assert violators == [], f"Direct openai import in retrieval/: {violators}"


def test_register_vector_not_in_retrieve():
    """register_vector must be called by get_conn(), not inside retrieve()."""
    base_path = (
        Path(__file__).resolve().parent.parent / "app" / "retrieval" / "base.py"
    )
    assert base_path.exists(), "app/retrieval/base.py not found"
    contents = base_path.read_text(encoding="utf-8")
    assert "register_vector" not in contents, (
        "register_vector must be called by get_conn(), not by retrieve(). "
        "See app/db.py lines 35-36."
    )


# ---------------------------------------------------------------------------
# Live-DB integration tests (skipped if Postgres unreachable)
# ---------------------------------------------------------------------------


def test_retrieve_returns_chunk_results(db_conn):
    """retrieve() against a live DB returns list[ChunkResult] (may be empty)."""
    from app.retrieval.base import ChunkResult, retrieve

    results = retrieve("Strat clean tone", k=8, conn=db_conn)
    assert isinstance(results, list)
    assert all(isinstance(r, ChunkResult) for r in results)
    assert len(results) <= 8


def test_alias_retrieval_parity(db_conn):
    """Shortform query and canonical query must return the same top chunk
    when both are alias-expanded before embedding."""
    from app.retrieval.base import retrieve

    results_short = retrieve("Strat clean tone", k=1, conn=db_conn)
    results_full = retrieve("Stratocaster clean tone", k=1, conn=db_conn)
    if not results_short or not results_full:
        pytest.skip("No chunks in DB — integration test requires ingested data")
    assert results_short[0].chunk_id == results_full[0].chunk_id, (
        "Shortform and canonical queries returned different top chunks "
        "after alias expansion"
    )
