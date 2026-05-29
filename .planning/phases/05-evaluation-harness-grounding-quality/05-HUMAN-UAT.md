---
status: partial
phase: 05-evaluation-harness-grounding-quality
source: [05-VERIFICATION.md]
started: 2026-05-29T00:00:00Z
updated: 2026-05-29T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Live retrieval scorer — recall@K + MRR + diff output
expected: First run of `python -m app.eval.retrieval` prints "(first run)" with recall@1/5/8 and MRR values. Second run prints signed-delta diff with direction arrows. `eval/runs.jsonl` gains one line per run.
result: [pending]

### 2. Live faithfulness CLI — RAGAS per-query scoring
expected: `python -m app.eval.ragas` (with live Postgres + ANTHROPIC_API_KEY + OPENAI_API_KEY) prints per-query faithfulness score for each held-out tuple, reports mean faithfulness, and `eval/faithfulness_runs.jsonl` grows by one record.
result: [pending]

### 3. Live refusal integration test — real Claude model refuses with empty context
expected: `ANTHROPIC_API_KEY=<key> python -m pytest tests/test_eval_refusal.py -m integration -q` passes — real Claude model refuses with empty context containing a phrase matching REFUSAL_PHRASES.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
