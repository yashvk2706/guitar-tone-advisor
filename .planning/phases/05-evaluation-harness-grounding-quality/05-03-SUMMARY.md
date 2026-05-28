---
phase: 05-evaluation-harness-grounding-quality
plan: "03"
subsystem: eval
tags: [eval, faithfulness, ragas, claim-decomposer, anthropic, tdd, jsonl]
dependency_graph:
  requires:
    - app/eval/schema.py
    - app/retrieval/base.py
    - app/generation/generator.py
    - app/generation/prompt.py
    - app/embeddings/factory.py
    - app/db.py
    - eval/golden_set.jsonl
  provides:
    - app/eval/ragas.py
    - tests/test_eval_ragas.py
    - eval/faithfulness_runs.jsonl (created on first live CLI run)
  affects:
    - eval/faithfulness_runs.jsonl (append-only)
tech_stack:
  added: []
  patterns:
    - two-step sync Anthropic claim decomposer (CLAIM_EXTRACT → CLAIM_SUPPORT)
    - asyncio.run() wrapper around async stream_response() in sync CLI context
    - system/user role separation for prompt-injection boundary (T-05-02)
    - parse_claims/parse_support with markdown-fence stripping + safe fallback to []
    - faithfulness(supported, total) returns 0.0 on total==0 (T-05-08 spoofing mitigation)
    - append-only JSONL log (faithfulness_runs.jsonl) separate from retrieval runs.jsonl
    - _FakeSyncClient with .messages.create() (distinct from _FakeAnthropicClient .stream())
    - import-inside-test-function for RED state pytest collection
key_files:
  created:
    - app/eval/ragas.py
    - tests/test_eval_ragas.py
  modified: []
decisions:
  - "Two distinct fake clients: _FakeSyncClient (has .messages.create()) for RAGAS unit tests; _FakeAnthropicClient (has .messages.stream()) for refusal tests. Never conflated (Pitfall 6)."
  - "Answer/claim text interpolated ONLY into user-role messages; CLAIM_EXTRACT_SYSTEM and CLAIM_SUPPORT_SYSTEM are fixed (T-05-02 prompt-injection boundary)."
  - "parse_claims returns [] and parse_support returns False on JSONDecodeError; faithfulness(0, 0) == 0.0 — failed extraction cannot masquerade as perfect score (T-05-08)."
  - "eval/faithfulness_runs.jsonl is separate from eval/runs.jsonl (A2) so Plan 01 diff reader (retrieval-shaped records) is never fed a faithfulness record."
  - "AsyncAnthropic used ONLY inside asyncio.run() wrapper for stream_response(); sync Anthropic client used for claim decomposition — two concerns kept separate."
  - "All 6 RAGAS tests implemented as offline pure-function tests with 0 asyncio.run() calls; live API calls only in CLI main()."
requirements-completed: [EVAL-04]
duration: 4min
completed: "2026-05-28"
---

# Phase 5 Plan 03: RAGAS-Style Faithfulness CLI Summary

**Two-step claim-decomposer faithfulness CLI (python -m app.eval.ragas) using the sync Anthropic client for claim extraction/grounding and asyncio.run() for live answer generation, logging supported_claims/total_claims per query to eval/faithfulness_runs.jsonl.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-28T18:31:00Z
- **Completed:** 2026-05-28T18:35:00Z
- **Tasks:** 3 (Task 1: RED, Task 2: GREEN + wiring, Task 3: verification — wiring was complete in Task 2)
- **Files modified:** 2

## Accomplishments

- `app/eval/ragas.py` — full RAGAS faithfulness CLI with parse helpers, claim decomposer, async→sync bridge, per-query scoring, and JSONL logging
- `tests/test_eval_ragas.py` — 6 offline unit/static tests covering all plan-specified behaviors; all pass GREEN
- 144 total tests pass (138 baseline + 6 new), 6 skipped (Postgres/API gated)

## Task Commits

1. **Task 1: Write failing RAGAS test stubs (RED)** — `566b408` (test)
2. **Task 2: Implement parse helpers + faithfulness scoring + CLI wiring (GREEN)** — `aa39917` (feat)

_Note: Task 3 (CLI wiring verification) required no additional code changes — main() and build_parser() were fully implemented in Task 2. Verification checks all passed._

## Files Created/Modified

- `app/eval/ragas.py` — Two-step claim decomposer CLI: `parse_claims`, `parse_support`, `faithfulness`, `generate_answer_sync`, `score_tuple_faithfulness`, `append_faithfulness_run`, `build_parser`, `main`
- `tests/test_eval_ragas.py` — 6 tests: `test_parse_claims`, `test_parse_claims_fenced`, `test_parse_support`, `test_faithfulness_score`, `test_ragas_cli_help`, `test_no_direct_openai_import`

## Decisions Made

- **_FakeSyncClient uses `.create()` not `.stream()`** — RAGAS claim decomposer uses the sync Anthropic client (non-streaming `.messages.create()`); this is fundamentally different from the streaming fake in test_generation.py. Kept completely separate per Pitfall 6.
- **Answer/claim text in user-role only** — `CLAIM_EXTRACT_USER` and `CLAIM_SUPPORT_USER` are the only places where `{answer}` and `{claim}` appear; system prompts are fixed strings that cannot carry injected content (T-05-02).
- **Safe parse fallbacks** — `parse_claims()` returns `[]` on failure; `parse_support()` returns `False` on failure; `faithfulness(0, 0)` returns `0.0`. An extraction failure cannot inflate the faithfulness score (T-05-08).
- **Separate faithfulness_runs.jsonl** — Plan 01's `format_diff` reads retrieval-specific fields from `eval/runs.jsonl`; faithfulness records use a different schema with `run_type`, `mean_faithfulness`, and `per_query`. Mixing in one file would break Plan 01's reader (A2 from RESEARCH.md).
- **asyncio.run() only in main() context** — Unit tests test pure functions directly (no event loop); asyncio.run() lives only in `generate_answer_sync()` which is called from CLI `main()` in a sync context.

## Deviations from Plan

None — plan executed exactly as written.

Task 3 (CLI wiring) was already complete as part of Task 2 implementation — `build_parser()` and `main()` were implemented together with the pure helpers. No additional code was needed; Task 3 was a verification-only step that confirmed all acceptance criteria.

## Known Stubs

None. All functions are fully implemented. `eval/faithfulness_runs.jsonl` is created on first live CLI run (requires ANTHROPIC_API_KEY + Postgres + OPENAI_API_KEY).

## Threat Flags

None. No new network endpoints, auth paths, or schema changes beyond what the plan's threat model covers.

Threats mitigated (per plan threat register):
- **T-05-02** (prompt injection): Answer/claim text only in user-role messages; system prompts are fixed. parse_claims returns [] on parse failure (suspicious-perfect-score signal).
- **T-05-08** (malformed JSON spoofing perfect faithfulness): parse_claims returns [] and parse_support returns False on JSONDecodeError; total==0 → faithfulness 0.0, not 1.0.
- **T-05-03** (embeddings abstraction leak): No direct openai import; all embedding via get_embedder(). test_no_direct_openai_import enforces this statically by scanning app/eval/ rglob.

## Self-Check: PASSED

- `app/eval/ragas.py`: FOUND (/Users/yashvinaykumar/Desktop/guitar-tone-advisor/app/eval/ragas.py)
- `tests/test_eval_ragas.py`: FOUND (/Users/yashvinaykumar/Desktop/guitar-tone-advisor/tests/test_eval_ragas.py)
- Task 1 commit 566b408: FOUND
- Task 2 commit aa39917: FOUND
- `venv/bin/python -m pytest tests/test_eval_ragas.py -q`: 6 passed
- `venv/bin/python -m pytest tests/ -q`: 144 passed, 6 skipped (no regressions)
- `venv/bin/python -m app.eval.ragas --help`: exits 0, lists --held-out, --all, --runs-log
- No direct openai import in app/eval/ragas.py (verified via test_no_direct_openai_import)

---
*Phase: 05-evaluation-harness-grounding-quality*
*Completed: 2026-05-28*
