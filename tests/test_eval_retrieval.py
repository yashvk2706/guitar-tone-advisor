"""Retrieval eval scorer tests — Phase 5 Plan 1.

8 named tests total: 7 offline unit + 1 live-DB integration (skipped when Postgres unavailable).

Covers:
  - recall_at_k() and reciprocal_rank() metric functions (EVAL-02)
  - append_run() / load_last_run() file helpers (EVAL-02)
  - format_diff() output format (EVAL-02)
  - CLI --help (EVAL-02)
  - Static guard: no f-string SQL in app/eval/retrieval.py (CLAUDE.md)
  - Live integration: scorer run against real DB (EVAL-02)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# DB-gated fixture (verbatim copy from tests/test_retrieval.py lines 44–62)
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
# Fake embedder for integration tests (verbatim copy from test_retrieval.py lines 94–112)
# ---------------------------------------------------------------------------


class _FakeEmbedder:
    model = "text-embedding-3-small"
    dim = 1536
    provider = "openai"

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 1536

    def embed_documents(self, texts):
        from app.embeddings.base import EmbeddingResult
        return EmbeddingResult(
            vectors=[[0.0] * 1536] * len(list(texts)),
            model=self.model, dim=self.dim, provider=self.provider,
        )


# ---------------------------------------------------------------------------
# Offline unit tests
# ---------------------------------------------------------------------------


def test_recall_at_k_hit():
    """recall_at_k returns 1.0 when any expected chunk appears in top-K."""
    from app.eval.retrieval import recall_at_k  # type: ignore[import-not-found]

    # Any-hit semantics: expected id at index 1 of retrieved → hit at k=8
    assert recall_at_k(["id-1"], ["id-2", "id-1", "id-3"], 8) == 1.0
    # Expected id at index 0 → hit at k=1
    assert recall_at_k(["id-1"], ["id-1", "id-2", "id-3"], 1) == 1.0
    # Multiple expected IDs — any hit counts
    assert recall_at_k(["id-1", "id-4"], ["id-2", "id-4", "id-3"], 8) == 1.0


def test_recall_at_k_miss():
    """recall_at_k returns 0.0 when no expected chunk is in top-K."""
    from app.eval.retrieval import recall_at_k  # type: ignore[import-not-found]

    # Expected id is not in top-K → miss
    assert recall_at_k(["id-z"], ["id-1", "id-2", "id-3"], 8) == 0.0
    # Pitfall 1 guard: recall@8 must never be less than recall@1 for the same id list
    ids_retrieved = ["id-2", "id-1", "id-3", "id-4", "id-5", "id-6", "id-7", "id-8"]
    expected = ["id-1"]
    r1 = recall_at_k(expected, ids_retrieved, 1)
    r8 = recall_at_k(expected, ids_retrieved, 8)
    assert r8 >= r1, f"recall@8={r8} < recall@1={r1} — any-hit semantics broken"


def test_mrr_calculation():
    """reciprocal_rank returns 1/rank of first hit, 0.0 on miss."""
    from app.eval.retrieval import reciprocal_rank  # type: ignore[import-not-found]

    # id-3 is at position 3 (1-indexed) → 1/3
    assert reciprocal_rank(["id-3"], ["id-1", "id-2", "id-3"]) == pytest.approx(1 / 3)
    # No hit → 0.0
    assert reciprocal_rank(["id-z"], ["id-1", "id-2", "id-3"]) == 0.0
    # First hit at rank 1 → 1.0
    assert reciprocal_rank(["id-1"], ["id-1", "id-2", "id-3"]) == pytest.approx(1.0)


def test_runs_jsonl_append(tmp_path):
    """append_run creates file + appends records; load_last_run returns last."""
    from app.eval.retrieval import append_run, load_last_run  # type: ignore[import-not-found]

    runs_path = tmp_path / "eval" / "runs.jsonl"

    # File does not exist yet — load_last_run returns None
    assert load_last_run(runs_path) is None

    # First append — file is created
    record1 = {"recall_at_1": 0.8, "recall_at_5": 0.8, "recall_at_8": 1.0, "mrr": 0.9, "k": 8}
    append_run(runs_path, record1)
    assert runs_path.exists()
    lines = [l for l in runs_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1

    # Second append — now 2 lines
    record2 = {"recall_at_1": 1.0, "recall_at_5": 1.0, "recall_at_8": 1.0, "mrr": 1.0, "k": 8}
    append_run(runs_path, record2)
    lines = [l for l in runs_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2

    # load_last_run returns the second record
    last = load_last_run(runs_path)
    assert last is not None
    assert last["recall_at_1"] == 1.0
    assert last["mrr"] == 1.0


def test_diff_first_run():
    """format_diff with no prior run contains '(first run)' and all metric labels."""
    from app.eval.retrieval import format_diff  # type: ignore[import-not-found]

    current = {"recall_at_1": 0.8, "recall_at_5": 0.8, "recall_at_8": 1.0, "mrr": 0.9}
    result = format_diff(current, None)
    assert "(first run)" in result
    assert "recall@1" in result
    assert "recall@5" in result
    assert "recall@8" in result
    assert "MRR" in result


def test_diff_with_prior():
    """format_diff with prior shows signed delta + direction arrow per D-11."""
    from app.eval.retrieval import format_diff  # type: ignore[import-not-found]

    prior = {"recall_at_1": 0.6, "recall_at_5": 0.6, "recall_at_8": 0.8, "mrr": 0.45}
    current = {"recall_at_1": 0.8, "recall_at_5": 0.8, "recall_at_8": 1.0, "mrr": 0.52}
    result = format_diff(current, prior)

    # Arrow for positive delta (increased metric)
    assert "↑" in result
    # Signed delta format: (+0.20 ↑)
    assert "+0.20" in result or "(+0.20" in result
    # Should contain → separator between prev and current values
    assert "→" in result
    # All metric labels present
    assert "recall@1" in result
    assert "recall@8" in result
    assert "MRR" in result

    # Test zero delta shows → arrow (no change)
    prior_same = {"recall_at_1": 0.8, "recall_at_5": 0.8, "recall_at_8": 1.0, "mrr": 0.52}
    result_same = format_diff(current, prior_same)
    # When delta is 0, the direction arrow is → (which we already check as separator)
    # so just confirm the format doesn't crash
    assert "recall@1" in result_same


def test_retrieval_cli_help():
    """build_parser --help lists required flags."""
    from app.eval.retrieval import build_parser  # type: ignore[import-not-found]

    # build_parser().parse_args(["--help"]) raises SystemExit OR format_help contains flags
    try:
        build_parser().parse_args(["--help"])
    except SystemExit:
        pass  # expected

    help_text = build_parser().format_help()
    assert "--held-out" in help_text
    assert "--all" in help_text
    assert "--k" in help_text


def test_no_fstring_sql_in_retrieval_scorer():
    """No f-string SQL in app/eval/retrieval.py (CLAUDE.md + T-05-04 constraint)."""
    scorer_path = Path(__file__).resolve().parent.parent / "app" / "eval" / "retrieval.py"
    assert scorer_path.exists(), "app/eval/retrieval.py not found"
    contents = scorer_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"""f["'][^"']*\{[^"']*(SELECT|INSERT|UPDATE|DELETE|TRUNCATE)[^"']*["']""",
        re.IGNORECASE,
    )
    offenders = [line for line in contents.splitlines() if pattern.search(line)]
    assert offenders == [], f"f-string SQL found in retrieval.py: {offenders}"


# ---------------------------------------------------------------------------
# Live-DB integration test (skipped when Postgres is unreachable)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_score_tuple_live(db_conn):
    """Live integration: score_tuple against real DB returns expected dict shape."""
    from app.eval.retrieval import score_tuple  # type: ignore[import-not-found]
    from app.eval.schema import load_golden_set

    golden_path = Path(__file__).resolve().parent.parent / "eval" / "golden_set.jsonl"
    if not golden_path.exists():
        pytest.skip("eval/golden_set.jsonl not found")

    tuples = load_golden_set(golden_path)
    held_out = [t for t in tuples if t.held_out]
    if not held_out:
        pytest.skip("No held-out tuples found in golden_set.jsonl")

    result = score_tuple(held_out[0], k=8, conn=db_conn, embedder=_FakeEmbedder())
    assert set(result.keys()) >= {"recall_at_1", "recall_at_5", "recall_at_8", "rr"}
    assert 0.0 <= result["recall_at_1"] <= 1.0
    assert 0.0 <= result["recall_at_5"] <= 1.0
    assert 0.0 <= result["recall_at_8"] <= 1.0
    assert 0.0 <= result["rr"] <= 1.0
