"""Retrieval recall scorer CLI — Phase 5 Plan 1 (EVAL-02).

Scores the golden eval set against the live HNSW retrieval layer, reports
recall@1/5/8 + MRR, appends each run to an append-only JSONL log, and prints
a per-metric diff vs the previous run.

Security constraints (CLAUDE.md + T-05-04):
  - This module NEVER writes raw SQL. All DB access is delegated to retrieve().
  - No direct openai import — route through get_embedder().
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.db import get_conn
from app.embeddings.factory import get_embedder
from app.eval.schema import GoldenTuple, load_golden_set
from app.retrieval.base import ChunkResult, retrieve


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------


def recall_at_k(expected_ids: list[str], retrieved_ids: list[str], k: int) -> float:
    """Return 1.0 if any expected chunk appears in the first k retrieved, else 0.0.

    Uses any-hit semantics: a single matching chunk in top-K counts as recalled.
    This matches how the golden eval set was authored — multiple expected chunks
    represent alternative relevant passages, not all-required.

    Args:
        expected_ids:  List of chunk IDs the human reviewer marked relevant.
        retrieved_ids: Ordered list of retrieved chunk IDs (best first).
        k:             Cutoff rank.

    Returns:
        1.0 if any expected id is in the top-k retrieved, else 0.0.
    """
    top_k_set = set(retrieved_ids[:k])
    return 1.0 if any(eid in top_k_set for eid in expected_ids) else 0.0


def reciprocal_rank(expected_ids: list[str], retrieved_ids: list[str]) -> float:
    """Return the reciprocal rank of the first hit among expected_ids in retrieved_ids.

    Returns 0.0 if no expected chunk appears in retrieved_ids at all.

    Args:
        expected_ids:  List of chunk IDs the human reviewer marked relevant.
        retrieved_ids: Ordered list of retrieved chunk IDs (best first, full k).

    Returns:
        1.0/rank of the first hit (rank is 1-indexed), or 0.0 if no hit.
    """
    expected_set = set(expected_ids)
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in expected_set:
            return 1.0 / rank
    return 0.0


# ---------------------------------------------------------------------------
# Tuple scorer (injectable deps for testing)
# ---------------------------------------------------------------------------


def score_tuple(
    t: GoldenTuple,
    k: int = 8,
    conn=None,
    embedder=None,
) -> dict:
    """Score a single golden tuple. Returns recall@1/5/8 and RR.

    conn=None → get_conn() is called inside retrieve().
    embedder=None → get_embedder() is called inside retrieve().
    Same injected-dependency pattern as retrieve() in app/retrieval/base.py.

    Args:
        t:        GoldenTuple to score.
        k:        Maximum retrieval depth (default 8, must be >= 8).
        conn:     Injected psycopg3 connection for testing.
        embedder: Injected Embedder instance for testing.

    Returns:
        dict with keys recall_at_1, recall_at_5, recall_at_8, rr.

    Raises:
        ValueError: If k < 8 — the fixed cutoffs (1, 5, 8) would produce
            misleading metric labels when k < 8 (WR-01 fix).
    """
    if k < 8:
        raise ValueError(
            f"k={k} is below the minimum required cutoff of 8. "
            "recall@8 requires at least k=8 retrieved results. "
            "Pass --k 8 or higher."
        )
    results: list[ChunkResult] = retrieve(t.query, k=k, conn=conn, embedder=embedder)
    retrieved_ids = [r.chunk_id for r in results]

    return {
        "recall_at_1": recall_at_k(t.expected_chunk_ids, retrieved_ids, 1),
        "recall_at_5": recall_at_k(t.expected_chunk_ids, retrieved_ids, 5),
        "recall_at_8": recall_at_k(t.expected_chunk_ids, retrieved_ids, 8),
        "rr": reciprocal_rank(t.expected_chunk_ids, retrieved_ids),
    }


# ---------------------------------------------------------------------------
# runs.jsonl helpers
# ---------------------------------------------------------------------------


def load_last_run(path: Path) -> dict | None:
    """Read the last non-empty line from runs.jsonl. Returns None if absent/empty.

    Args:
        path: Path to the runs JSONL log file.

    Returns:
        Parsed dict of the last record, or None if file absent or empty.
    """
    if not path.exists():
        return None
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(lines[-1]) if lines else None


def append_run(path: Path, record: dict) -> None:
    """Append one JSON record as a line to path, creating the file if absent.

    Mirrors the file-open convention from app/eval/schema.py (ensure_ascii=False,
    encoding=utf-8, path.parent.mkdir(parents=True, exist_ok=True)).

    Args:
        path:   Path to the runs JSONL log file.
        record: Dict to serialize as a JSON line.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Diff formatter
# ---------------------------------------------------------------------------


def format_diff(current: dict, prior: dict | None) -> str:
    """Format recall/MRR diff per D-11.

    First run (no prior): shows current metrics only with '(first run)'.
    Subsequent runs: shows prev → curr (delta arrow) for each metric.

    Args:
        current: Current run metrics dict (recall_at_1/5/8, mrr).
        prior:   Prior run metrics dict, or None if this is the first run.

    Returns:
        Formatted diff string for stdout display.
    """
    if prior is None:
        return (
            f"recall@1: {current['recall_at_1']:.2f}  "
            f"recall@5: {current['recall_at_5']:.2f}  "
            f"recall@8: {current['recall_at_8']:.2f}  "
            f"MRR: {current['mrr']:.2f}  (first run)"
        )

    parts = []
    for key, label in [
        ("recall_at_1", "recall@1"),
        ("recall_at_5", "recall@5"),
        ("recall_at_8", "recall@8"),
        ("mrr", "MRR"),
    ]:
        # Use .get() so a missing or schema-mismatched prior record (e.g. hand-
        # edited, future schema change) renders "n/a" rather than raising KeyError
        # (WR-02 fix).
        prev_val = prior.get(key)
        curr_val = current[key]
        if prev_val is None:
            parts.append(f"{label}: n/a → {curr_val:.2f}")
        else:
            delta = curr_val - prev_val
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            parts.append(f"{label}: {prev_val:.2f} → {curr_val:.2f} ({delta:+.2f} {arrow})")

    return "  ".join(parts)


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    p = argparse.ArgumentParser(
        prog="python -m app.eval.retrieval",
        description=(
            "Retrieval recall scorer CLI (EVAL-02). "
            "Scores the golden eval set against the live HNSW retrieval layer, "
            "reports recall@1/5/8 + MRR, appends each run to eval/runs.jsonl, "
            "and prints a per-metric diff vs the previous run."
        ),
    )
    p.add_argument(
        "--held-out",
        action="store_true",
        default=True,
        help="Score only the 5 held-out tuples (default).",
    )
    p.add_argument(
        "--all",
        dest="held_out",
        action="store_false",
        help="Score all 22 tuples instead of just the 5 held-out ones.",
    )
    p.add_argument(
        "--k",
        type=int,
        default=8,
        help=(
            "Maximum retrieval depth for recall@K (default: 8, minimum: 8). "
            "Must be >= 8 because recall@8 is one of the fixed scoring cutoffs. "
            "Values below 8 raise ValueError to prevent misleading metric labels."
        ),
    )
    p.add_argument(
        "--golden-set",
        type=Path,
        default=Path("eval/golden_set.jsonl"),
        help="Path to the JSONL golden eval set (default: eval/golden_set.jsonl).",
    )
    p.add_argument(
        "--runs-log",
        type=Path,
        default=Path("eval/runs.jsonl"),
        help="Path to the append-only runs log (default: eval/runs.jsonl).",
    )
    return p


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the retrieval scorer CLI.

    Loads the golden eval set, scores each tuple via retrieve(), aggregates
    metrics, prints a diff vs the prior run, and appends the new run record
    to runs.jsonl.

    Args:
        argv: CLI argument list (None → sys.argv).

    Returns:
        0 on success.
    """
    args = build_parser().parse_args(argv)

    # Fail-fast: construct embedder BEFORE opening the DB connection.
    # A factory error (unknown EMBEDDING_MODEL) should fail before Postgres.
    embedder = get_embedder()

    conn = get_conn()
    try:
        # Load and filter golden tuples
        tuples = load_golden_set(args.golden_set)
        if args.held_out:
            tuples = [t for t in tuples if t.held_out]
            scope = "held_out"
        else:
            scope = "all"

        if not tuples:
            print(
                f"No tuples found (scope={scope!r}). "
                "Check eval/golden_set.jsonl exists and has held_out tuples.",
                file=sys.stderr,
            )
            return 1

        # Score each tuple
        scores = [score_tuple(t, k=args.k, conn=conn, embedder=embedder) for t in tuples]

        # Aggregate mean metrics
        n = len(scores)
        recall_at_1 = sum(s["recall_at_1"] for s in scores) / n
        recall_at_5 = sum(s["recall_at_5"] for s in scores) / n
        recall_at_8 = sum(s["recall_at_8"] for s in scores) / n
        mrr = sum(s["rr"] for s in scores) / n

        current_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "k": args.k,
            "scope": scope,
            "recall_at_1": recall_at_1,
            "recall_at_5": recall_at_5,
            "recall_at_8": recall_at_8,
            "mrr": mrr,
            "embedding_model": get_settings().embedding_model,
        }

        # Load prior run for diff — only compare if scopes match (WR-03 fix).
        # Comparing held_out metrics against all-set metrics produces a delta
        # with no statistical meaning; warn and suppress the diff instead.
        prior_raw = load_last_run(args.runs_log)
        if prior_raw and prior_raw.get("scope") != scope:
            print(
                f"  (prior run scope={prior_raw.get('scope')!r} differs from "
                f"current scope={scope!r} — no diff shown)",
                file=sys.stderr,
            )
            prior = None
        else:
            prior = prior_raw

        # Print diff to stdout
        print(format_diff(current_record, prior))

        # Append this run to the log
        append_run(args.runs_log, current_record)

        return 0

    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":  # pragma: no cover — invoked via python -m
    sys.exit(main())
