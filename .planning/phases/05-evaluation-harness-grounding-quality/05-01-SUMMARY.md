---
phase: 05-evaluation-harness-grounding-quality
plan: "01"
subsystem: eval
tags: [eval, retrieval, recall, mrr, cli, jsonl, tdd]
dependency_graph:
  requires:
    - app/eval/schema.py
    - app/retrieval/base.py
    - app/embeddings/factory.py
    - app/db.py
    - eval/golden_set.jsonl
  provides:
    - app/eval/retrieval.py
    - tests/test_eval_retrieval.py
    - eval/runs.jsonl (created on first live CLI run)
  affects:
    - eval/runs.jsonl (append-only)
tech_stack:
  added: []
  patterns:
    - any-hit recall@K semantics
    - reciprocal rank (MRR)
    - inject-or-singleton (conn=None / embedder=None)
    - append-only JSONL log with load_last_run / append_run
    - format_diff with signed delta + direction arrow
    - static f-string-SQL guard test
    - import-inside-test-function for RED state collection
key_files:
  created:
    - app/eval/retrieval.py
    - tests/test_eval_retrieval.py
  modified: []
decisions:
  - "Any-hit semantics for recall_at_k: 1.0 if any expected chunk in top-K (not all-hit). Matches golden set authoring intent — multiple expected chunks represent alternatives, not required-all."
  - "score_tuple() delegates exclusively to retrieve() — no raw SQL in scorer. T-05-04 enforced by static test_no_fstring_sql_in_retrieval_scorer."
  - "Fail-fast embedder construction before get_conn() in main() — a factory error (unknown EMBEDDING_MODEL) fails before touching Postgres."
  - "Per D-10: runs.jsonl record carries timestamp (ISO-8601 UTC), k, scope, recall_at_1, recall_at_5, recall_at_8, mrr, embedding_model."
  - "format_diff per D-11: first run shows metrics + '(first run)'; subsequent runs show 'prev → curr (+delta arrow)' for each metric."
metrics:
  duration_minutes: 15
  completed_date: "2026-05-28"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 5 Plan 01: Retrieval Recall Scorer CLI Summary

**One-liner:** Recall@1/5/8 + MRR scorer CLI with any-hit semantics, append-only runs.jsonl logging, and signed-delta diff output against the live HNSW retrieval layer.

## What Was Built

### app/eval/retrieval.py

Retrieval scorer CLI (`python -m app.eval.retrieval`) implementing:

- `recall_at_k(expected_ids, retrieved_ids, k)` — any-hit semantics: 1.0 if any expected chunk appears in top-K, else 0.0.
- `reciprocal_rank(expected_ids, retrieved_ids)` — 1/rank of first hit, 0.0 on miss.
- `score_tuple(t, k=8, conn=None, embedder=None)` — inject-or-singleton pattern; calls `retrieve()` exclusively (no raw SQL).
- `load_last_run(path)` / `append_run(path, record)` — append-only JSONL log helpers.
- `format_diff(current, prior)` — D-11 format: first run shows metrics + "(first run)"; subsequent runs show `recall@8: 0.60 → 0.80 (+0.20 ↑)` shape.
- `build_parser()` — `--held-out` (default, scores 5 held-out tuples), `--all` (scores all 22), `--k`, `--golden-set`, `--runs-log`.
- `main(argv=None)` — fail-fast embedder before get_conn(), load + filter golden set, score each tuple, aggregate mean metrics, print diff, append run record.

### tests/test_eval_retrieval.py

9 tests (8 offline unit/static + 1 live-DB integration):

| Test | Coverage |
|------|----------|
| test_recall_at_k_hit | Any-hit semantics, multi-expected-id case |
| test_recall_at_k_miss | Miss case + Pitfall 1 guard (recall@8 >= recall@1) |
| test_mrr_calculation | reciprocal_rank 1/3, 0.0 miss, 1.0 first-hit |
| test_runs_jsonl_append | File creation, 2-append, load_last_run returns last |
| test_diff_first_run | "(first run)" + all 4 metric labels |
| test_diff_with_prior | Signed delta, ↑ arrow, → separator |
| test_retrieval_cli_help | build_parser --help has --held-out, --all, --k |
| test_no_fstring_sql_in_retrieval_scorer | Static scan — T-05-04 mitigation |
| test_score_tuple_live | Live-DB integration (skips when Postgres unreachable) |

## Verification Results

```
venv/bin/python -m pytest tests/test_eval_retrieval.py -k "not integration" -q
→ 8 passed, 1 deselected

venv/bin/python -m pytest tests/ -q
→ 135 passed, 5 skipped (no regressions vs 126-test baseline)

venv/bin/python -m app.eval.retrieval --help
→ exits 0, lists --held-out, --all, --k, --golden-set, --runs-log

grep -nE 'import openai|from openai' app/eval/retrieval.py
→ no matches (CLAUDE.md constraint satisfied)
```

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written.

The one minor difference: the plan's acceptance criteria said "exactly 8 tests" but the action text specified 7 named unit tests + 1 static guard + 1 live integration = 9 total. The collected suite shows 9 tests (8 offline + 1 live integration skipped), which matches the action description. The 8-vs-9 discrepancy was a counting inconsistency in the plan artifact — the implementation follows the action text.

## Known Stubs

None. All functions are fully implemented. `eval/runs.jsonl` is created on first live CLI run (requires Postgres + OPENAI_API_KEY).

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes introduced beyond what the plan's threat model covers.

Threats in scope (per plan):
- T-05-04 (SQL injection): mitigated — scorer calls `retrieve()` exclusively; static test enforces this.
- T-05-05 (chunk ID tampering): accepted — UUID validation at load time in schema.py.
- T-05-06 (credential disclosure): accepted — get_embedder()/get_conn() own credential handling.

## Self-Check: PASSED

- `app/eval/retrieval.py`: FOUND (/Users/yashvinaykumar/Desktop/guitar-tone-advisor/app/eval/retrieval.py)
- `tests/test_eval_retrieval.py`: FOUND (/Users/yashvinaykumar/Desktop/guitar-tone-advisor/tests/test_eval_retrieval.py)
- Task 1 commit 3737d12: FOUND
- Task 2 commit 77e2d5b: FOUND
