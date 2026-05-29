---
phase: 05-evaluation-harness-grounding-quality
verified: 2026-05-29T00:00:00Z
status: human_needed
score: 3/3
overrides_applied: 0
human_verification:
  - test: "Run `python -m app.eval.retrieval` twice against live Postgres + OPENAI_API_KEY"
    expected: "First run prints '(first run)' with recall@1/5/8 and MRR values; second run prints signed-delta diff with direction arrows; eval/runs.jsonl has one line per run"
    why_human: "Requires live Postgres + OPENAI_API_KEY; cannot run in offline verification"
  - test: "Run `python -m app.eval.ragas` against live Postgres + ANTHROPIC_API_KEY + OPENAI_API_KEY"
    expected: "Per-query faithfulness score printed for each held-out tuple; mean faithfulness reported; eval/faithfulness_runs.jsonl grows by one record"
    why_human: "Requires live Postgres + both API keys; all offline tests pass but live CLI path cannot be verified programmatically"
  - test: "Run `ANTHROPIC_API_KEY=<key> python -m pytest tests/test_eval_refusal.py -m integration -q`"
    expected: "test_live_empty_context_produces_refusal passes — real Claude model refuses with empty context containing a phrase matching REFUSAL_PHRASES"
    why_human: "Requires a real ANTHROPIC_API_KEY; integration test currently skipped"
---

# Phase 5: Evaluation Harness & Grounding Quality Verification Report

**Phase Goal:** Every future retrieval or prompt change can be judged against the held-out golden eval set authored in Phase 1 and a faithfulness score — no more vibes-based tuning, and the empty-context refusal contract is enforced by an automated smoke test.
**Verified:** 2026-05-29T00:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running `python -m app.eval.retrieval` loads `eval/golden_set.jsonl`, prints recall@1/5/8 + MRR, and appends a record to `eval/runs.jsonl` after each retrieval configuration change | VERIFIED (offline) / human needed (live) | `app/eval/retrieval.py` exists (347 lines); `load_golden_set`, `recall_at_k`, `reciprocal_rank`, `score_tuple`, `format_diff`, `append_run` all fully implemented; CLI `--help` exits 0 listing `--held-out`, `--all`, `--k`, `--golden-set`, `--runs-log`; `eval/golden_set.jsonl` exists with 22 tuples (5 held-out); 8 offline unit tests pass; live run requires Postgres + OPENAI_API_KEY |
| 2 | An automated smoke test passes when, given `retrieved_chunks=[]`, the generation layer returns a refusal (no fabricated knob settings, no hallucinated gear names) | VERIFIED | `tests/test_eval_refusal.py` has 4 tests; 3 offline pass (test_empty_context_refusal_assertion, test_empty_context_produces_refusal, test_adversarial_mismatch_no_knobs); tests call `stream_response()` directly via `asyncio.run()`, never via HTTP; `_KNOB_RE` + `REFUSAL_PHRASES` assertion machinery confirmed working; live integration gated on ANTHROPIC_API_KEY (currently skipped) |
| 3 | Running `python -m app.eval.ragas` on a sample of generated answers prints a faithfulness score and logs per-claim support evidence | VERIFIED (offline) / human needed (live) | `app/eval/ragas.py` exists (474 lines); `parse_claims`, `parse_support`, `faithfulness`, `generate_answer_sync`, `score_tuple_faithfulness`, `append_faithfulness_run`, `build_parser`, `main` all implemented; CLI `--help` exits 0 listing `--held-out`, `--all`, `--runs-log` with default `eval/faithfulness_runs.jsonl`; 6 offline unit tests pass; live run requires ANTHROPIC_API_KEY + Postgres + OPENAI_API_KEY |

**Score:** 3/3 truths verified (offline components); 3 human verification items for live API-gated paths

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/eval/retrieval.py` | Recall@K + MRR scorer CLI with runs.jsonl logging and diff output | VERIFIED | 347 lines; all 8 exported functions present: `recall_at_k`, `reciprocal_rank`, `score_tuple`, `load_last_run`, `append_run`, `format_diff`, `build_parser`, `main`; no raw SQL; no openai import |
| `tests/test_eval_retrieval.py` | 9 tests: 8 offline unit/static + 1 live-DB integration | VERIFIED | 9 tests collected; 8 offline pass, 1 integration skipped (Postgres unreachable); all named tests present including `test_no_fstring_sql_in_retrieval_scorer` |
| `eval/golden_set.jsonl` | 22 tuples (5 held-out) — authored in Phase 1 | VERIFIED | File exists at `eval/golden_set.jsonl`; 22 tuples total, 5 with `held_out=true`; keys: query, expected_chunk_ids, expected_themes, held_out |
| `tests/test_eval_refusal.py` | 4 refusal smoke tests: 3 offline unit + 1 live integration | VERIFIED | 4 tests collected; 3 offline pass, 1 integration skipped (ANTHROPIC_API_KEY not set); `asyncio.run` count = 3; no TestClient/httpx/HTTP usage |
| `app/eval/ragas.py` | Two-step claim-decomposer faithfulness CLI | VERIFIED | 474 lines; `parse_claims`, `parse_support`, `faithfulness`, `generate_answer_sync`, `score_tuple_faithfulness`, `append_faithfulness_run`, `build_parser`, `main` all present; no openai import; answer/claim text only in user-role messages |
| `tests/test_eval_ragas.py` | 6 tests: 5 offline unit/static + faithfulness scoring | VERIFIED | 6 tests collected; all 6 pass; `_FakeSyncClient` uses `.messages.create()` not `.messages.stream()` (Pitfall 6 avoided) |
| `eval/faithfulness_runs.jsonl` | Created on first live CLI run | NOT YET CREATED | Expected — created only on first live run requiring ANTHROPIC_API_KEY + Postgres; not a blocker per plan |
| `eval/runs.jsonl` | Created on first live CLI run | NOT YET CREATED | Expected — created only on first live run requiring Postgres + OPENAI_API_KEY; not a blocker per plan |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `app/eval/retrieval.py::score_tuple` | `app/retrieval/base.py::retrieve` | `retrieve(t.query, k=k, conn=conn, embedder=embedder)` | WIRED | Line 106: `results: list[ChunkResult] = retrieve(t.query, k=k, conn=conn, embedder=embedder)` |
| `app/eval/retrieval.py` | `app/eval/schema.py::load_golden_set` | `load_golden_set(path)` then filter on `t.held_out` | WIRED | Lines 23, 280: `from app.eval.schema import GoldenTuple, load_golden_set`; `tuples = load_golden_set(args.golden_set)` |
| `app/eval/retrieval.py::main` | `eval/runs.jsonl` | `append_run()` after `load_last_run()` diff | WIRED | Lines 319, 334: `prior_raw = load_last_run(args.runs_log)`; `append_run(args.runs_log, current_record)` |
| `tests/test_eval_refusal.py` | `app/generation/generator.py::stream_response` | `asyncio.run(_collect(client, sources_with_ids))` | WIRED | Lines 143, 147: `from app.generation.generator import stream_response`; `async for sse in stream_response(...)` |
| `tests/test_eval_refusal.py` | `app/generation/prompt.py` | `build_system_blocks()` + `build_messages()` | WIRED | Lines 144-145: `from app.generation.prompt import build_system_blocks, build_messages` |
| `tests/test_eval_refusal.py adversarial case` | `app/retrieval/base.py::ChunkResult` | inline lo-fi `ChunkResult(...)` constructed as `(chunk, sn)` tuples | WIRED | Line 23: `from app.retrieval.base import ChunkResult`; ChunkResult constructed at line 221 |
| `app/eval/ragas.py::generate_answer_sync` | `app/generation/generator.py::stream_response` | `asyncio.run()` wrapper around async generator | WIRED | Line 213: `return asyncio.run(_run())`; stream_response called at line 200 |
| `app/eval/ragas.py` | `app/retrieval/base.py::retrieve` | `retrieve(t.query, k=k, conn=conn, embedder=embedder)` | WIRED | Line 250: `chunks: list[ChunkResult] = retrieve(t.query, k=k, conn=conn, embedder=embedder)` |
| `app/eval/ragas.py claim decomposer` | `anthropic.Anthropic().messages.create` | sync client, system+user role separation, two calls per tuple | WIRED | Lines 257, 278: `sync_client.messages.create(model=..., system=CLAIM_EXTRACT_SYSTEM, messages=[...])` and support check per claim |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `app/eval/retrieval.py` | `tuples` (golden set), `scores` (recall metrics) | `load_golden_set(args.golden_set)` → `retrieve()` → `recall_at_k()`/`reciprocal_rank()` | Yes — reads from `eval/golden_set.jsonl` and live HNSW DB | FLOWING (offline parse path confirmed; live DB path requires Postgres) |
| `app/eval/ragas.py` | `claims` (from LLM), `supported_count` (per-claim grounding) | `generate_answer_sync()` → `parse_claims()` → `parse_support()` per claim | Yes — live LLM calls produce real data; `faithfulness(0, 0) == 0.0` guards total==0 | FLOWING (offline helpers confirmed; live LLM path requires API keys) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `recall_at_k` any-hit semantics | `python -c "from app.eval.retrieval import recall_at_k; print(recall_at_k(['a'], ['b','a'], 8))"` | `1.0` | PASS |
| `recall_at_k` miss case | `python -c "from app.eval.retrieval import recall_at_k; print(recall_at_k(['a'], ['b','c'], 8))"` | `0.0` | PASS |
| `parse_claims` bare JSON | `python -c "from app.eval.ragas import parse_claims; print(parse_claims('[\"a\",\"b\"]'))"` | `['a', 'b']` | PASS |
| `parse_support` true case | `python -c "from app.eval.ragas import parse_support; print(parse_support('{\"supported\": true}'))"` | `True` | PASS |
| `faithfulness` zero-total guard | `python -c "from app.eval.ragas import faithfulness; print(faithfulness(0, 0))"` | `0.0` | PASS |
| `retrieval CLI --help` | `python -m app.eval.retrieval --help` | exits 0; lists `--held-out`, `--all`, `--k`, `--golden-set`, `--runs-log` | PASS |
| `ragas CLI --help` | `python -m app.eval.ragas --help` | exits 0; lists `--held-out`, `--all`, `--runs-log` with default `eval/faithfulness_runs.jsonl` | PASS |
| Offline test suite (all 3 eval files) | `python -m pytest tests/test_eval_retrieval.py tests/test_eval_refusal.py tests/test_eval_ragas.py -q` | 18 passed, 1 skipped | PASS |
| Full suite (145 tests per prompt spec) | `python -m pytest tests/ -q` | 145 passed, 5 skipped | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| EVAL-02 | 05-01-PLAN.md | Recall@K and MRR computed against golden eval set, logged after each retrieval configuration change | SATISFIED | `app/eval/retrieval.py` implements scorer + JSONL logger; 8 offline tests pass; CLI --help verified; `eval/golden_set.jsonl` (22 tuples, 5 held-out) exists from Phase 1 |
| EVAL-03 | 05-02-PLAN.md | Empty-context smoke test verifies model produces refusal (not hallucinated answer) when zero chunks retrieved | SATISFIED | `tests/test_eval_refusal.py` has 3 offline refusal tests; `test_empty_context_produces_refusal` and `test_adversarial_mismatch_no_knobs` both pass; live integration gated on ANTHROPIC_API_KEY (skipped) |
| EVAL-04 | 05-03-PLAN.md | RAGAS faithfulness scoring computed on sample of generated answers to measure hallucination rate | SATISFIED | `app/eval/ragas.py` implements two-step claim decomposer CLI; 6 offline tests pass; `faithfulness = supported_claims / total_claims`; REQUIREMENTS.md traceability table marks this Complete |

**Note:** REQUIREMENTS.md checkbox status shows EVAL-02 and EVAL-03 as `[ ]` (Pending) while the traceability table at the bottom still marks them with "Pending" in the Status column. The implementations are complete and tests pass. This is a documentation artifact — the checkbox and traceability table were not updated after Phase 5 completion. Not a blocker since the implementations exist and work.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `app/eval/ragas.py` | 114, 116, 118 | `return []` | Info | These are intentional safe-fallback returns inside `parse_claims()` on JSON parse failure — not stubs. No real data is flowing to empty returns. T-05-08 mitigation design. |
| `tests/test_eval_retrieval.py` | 215 | `@pytest.mark.integration` (unregistered) | Info | Cosmetic PytestUnknownMarkWarning — integration test still skips correctly via the `db_conn` fixture. Not a blocker. |
| `tests/test_eval_refusal.py` | 254 | `@pytest.mark.integration` (unregistered) | Info | Same as above — skips correctly via `anthropic_key` fixture. |

No TBD, FIXME, or XXX markers found in any Phase 5 files. No placeholder patterns. No forbidden openai imports in `app/eval/`.

### Human Verification Required

#### 1. Live Retrieval Scorer Run

**Test:** With Postgres running and OPENAI_API_KEY set, run `python -m app.eval.retrieval` twice from the repo root.
**Expected:** First run prints recall@1/5/8 + MRR metrics with "(first run)"; second run prints signed-delta diff with ↑/↓/→ arrows for each metric; `eval/runs.jsonl` gains one line per run; each line is valid JSON with keys: timestamp, k, scope, recall_at_1, recall_at_5, recall_at_8, mrr, embedding_model.
**Why human:** Requires live Postgres + OPENAI_API_KEY for embedding; cannot test in offline verification.

#### 2. Live Faithfulness CLI Run

**Test:** With Postgres, OPENAI_API_KEY, and ANTHROPIC_API_KEY all set, run `python -m app.eval.ragas` from the repo root.
**Expected:** Per-query faithfulness score printed for each of the 5 held-out tuples (e.g. `'get that bb king tone...': faithfulness=0.85 (5/6 claims supported)`); mean faithfulness printed; `eval/faithfulness_runs.jsonl` gains one record with keys: timestamp, run_type="faithfulness", scope, sample_count, mean_faithfulness, per_query, embedding_model, anthropic_model.
**Why human:** Requires live Postgres + both API keys; all offline parse/scoring tests pass but end-to-end answer generation + claim decomposition is entirely live-API-dependent.

#### 3. Live Refusal Integration Test

**Test:** Set ANTHROPIC_API_KEY and run `python -m pytest tests/test_eval_refusal.py -m integration -q`.
**Expected:** `test_live_empty_context_produces_refusal` passes — the real Claude model, given empty `sources_with_ids=[]`, produces text containing at least one of the REFUSAL_PHRASES: `"I don't have material"` or `"the closest I have"`.
**Why human:** Requires a real ANTHROPIC_API_KEY; the test is intentionally gated; it tests actual LLM behavior rather than a fake client.

### Gaps Summary

No gaps. All offline-verifiable must-haves are satisfied:
- `app/eval/retrieval.py` is fully implemented and wired to `retrieve()`, `load_golden_set()`, and the runs.jsonl log.
- `tests/test_eval_refusal.py` enforces the empty-context and adversarial-mismatch refusal contracts via direct `stream_response()` calls (not HTTP).
- `app/eval/ragas.py` implements the faithfulness CLI with `parse_claims`/`parse_support` handling bare + fenced JSON with safe fallbacks.
- The full test suite runs at 145 passed, 5 skipped — no regressions.
- The three live-API-dependent behaviors (retrieval runner, faithfulness runner, live refusal integration) require human verification with real API credentials.

**REQUIREMENTS.md checkbox discrepancy:** EVAL-02 and EVAL-03 are marked `[ ]` in REQUIREMENTS.md but their implementations are verified in the codebase. This is a documentation artifact requiring a manual checkbox update — not a code gap.

---

_Verified: 2026-05-29T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
