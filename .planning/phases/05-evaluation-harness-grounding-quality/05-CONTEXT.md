# Phase 5: Evaluation Harness & Grounding Quality - Context

**Gathered:** 2026-05-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the eval tooling that lets every future retrieval or prompt change be measured objectively: a retrieval recall scorer against the existing golden eval set, automated generation refusal contract enforcement, and a custom LLM-based faithfulness pipeline.

**In scope:** `app/eval/retrieval.py` CLI (recall@K + MRR against `eval/golden_set.jsonl`); `tests/test_eval_refusal.py` (empty-context + adversarial-mismatch smoke tests); `app/eval/ragas.py` CLI (faithfulness score via custom claim decomposer); `eval/runs.jsonl` append-only metric log.

**Out of scope:** Corpus expansion (PDF/article/YouTube ingestion — later milestone), hybrid tsvector+RRF retrieval, UI changes, authoring more golden tuples (already done in Phase 1), the `ragas` Python library or any LangChain/LlamaIndex dependency.

</domain>

<decisions>
## Implementation Decisions

### Retrieval Scoring Scope
- **D-01:** Configurable scope via `--held-out` flag (default: held-out 5 tuples only; `--all` uses all 22). Default enforces the clean held-out contract from `eval/HELD_OUT.md` — those 5 queries were locked before any Phase 2 retrieval tuning. The `--all` flag allows comparison to quantify data-leakage risk on the remaining 17 tuples.
- **D-02:** Report recall@1, recall@5, recall@8 + MRR. Covers the deployed K=8 cutoff, a mid-range check, and top-1 precision. Enough signal to catch a regression without overwhelming output.
- **D-03:** Live DB + embedder when invoked as CLI (`conn=None`, `embedder=None` → `get_conn()` + `get_embedder()`). Injected dependencies for unit tests — same pattern as `retrieve()` in `app/retrieval/base.py`. Scorer logic has unit tests; integration run requires live Postgres + OpenAI key.

### RAGAS Faithfulness Pipeline
- **D-04:** Custom LLM-based claim decomposer using the existing `anthropic` client — **no `ragas` library, no LangChain, no HuggingFace deps**. CLAUDE.md no-framework constraint applies here. Two-step pipeline per query: (1) extract factual claims from the answer via one `anthropic` call, (2) check each claim against the retrieved chunk texts. Faithfulness score = supported_claims / total_claims.
- **D-05:** Generate answers live via the Anthropic API during the eval run. `asyncio.run()` wrapper around `stream_response()`. No pre-generated answer cache — the eval always reflects the current prompt + model.
- **D-06:** Sample = all held-out 5 tuples (consistent with the retrieval scorer). Each query costs ~2 Anthropic API calls (generate answer + claim-check).

### Refusal Smoke Tests
- **D-07:** Two tiers: offline mock tests (monkeypatched `_FakeAnthropicClient` that streams a pre-canned fabricated response) run in every pytest invocation; one live integration test (skipped unless `ANTHROPIC_API_KEY` set) mirrors the `db_conn`-gated pattern from Phase 2 tests.
- **D-08:** Both test cases in Plan 2 scope: (1) **empty-context** — `retrieved_chunks=[]`; (2) **adversarially mismatched** — inject chunks from an unrelated topic (e.g., lo-fi tone chunks given an EVH gain query).
- **D-09:** Refusal assertion = check response text for exact phrases from `SYSTEM_PROMPT_TEXT` rule 2: `"I don't have material"` or `"the closest I have"`. For the adversarial case: additionally assert that no knob-setting pattern (e.g., `Gain: 7`, `Bass=6`) appears in the response — the model should not fabricate settings from unrelated sources.

### runs.jsonl Schema & CLI Output
- **D-10:** Per-run fields: `{timestamp (ISO-8601 UTC), k, scope ("held_out" | "all"), recall_at_1, recall_at_5, recall_at_8, mrr, embedding_model}`. Captures what was tested and enough to diagnose why two runs with the same K differ (e.g., different embedding model).
- **D-11:** CLI diff output shows delta per metric with direction arrow vs. the previous run in `eval/runs.jsonl`. Format: `recall@8: 0.60 → 0.80 (+0.20 ↑)  MRR: 0.45 → 0.52 (+0.07 ↑)`. First run shows current numbers only (no prior to compare).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Eval Data
- `eval/golden_set.jsonl` — 22 GoldenTuples; `held_out: true` flags the 5 held-out tuples (indices 0, 2, 4, 8, 11)
- `eval/HELD_OUT.md` — Locked held-out split with ISO-8601 timestamp and audit statement. The 5 held-out queries are the primary scoring target.
- `eval/QUERIES.md` — Original draft queries (for reference only — do not re-author tuples)

### Existing Eval Infrastructure
- `app/eval/schema.py` — `GoldenTuple`, `load_golden_set()`, `save_golden_set()`, `VALID_THEMES` — reuse these; do not re-implement
- `app/eval/author.py` — Phase 1 authoring CLI; not consumed by Phase 5 but shows the DB query pattern for chunk lookup

### Retrieval Layer
- `app/retrieval/base.py` — `retrieve()` with injected `conn` + `embedder` params; `ChunkResult` frozen dataclass with `chunk_id`, `text`, `distance` fields
- `app/retrieval/aliases.py` — `expand_query()` — already called inside `retrieve()`; scorer invokes `retrieve()` directly

### Generation Layer
- `app/generation/generator.py` — `stream_response()` async generator; call via `asyncio.run()` wrapper in eval scripts
- `app/generation/prompt.py` — `SYSTEM_PROMPT_TEXT` (contains exact refusal phrases: "I don't have material" / "the closest I have"), `build_system_blocks()`, `build_sources_xml()`, `build_messages()`

### Project Constraints
- `CLAUDE.md` — No `ragas` library, no LangChain, no LlamaIndex. All LLM calls via direct `anthropic` SDK. Embedder Protocol: never import `openai` directly.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/eval/schema.py::load_golden_set(path)` — already tested; returns `list[GoldenTuple]`. Filter on `t.held_out` for held-out scope.
- `app/retrieval/base.py::retrieve(query, k, conn=None, embedder=None)` — injected deps for testing; returns `list[ChunkResult]` ordered by ascending cosine distance. `ChunkResult.chunk_id` is a UUID string.
- `app/generation/generator.py::stream_response(...)` — async generator; use `asyncio.run()` + accumulator to collect full answer text for faithfulness eval.
- `app/generation/prompt.py::build_system_blocks()`, `build_sources_xml()`, `build_messages()` — required to construct the exact inputs `stream_response()` expects.

### Established Patterns
- **Injected-dep test isolation:** `conn=None` → `get_conn()`, `embedder=None` → `get_embedder()`. Same pattern in `retrieve()`. Apply to retrieval scorer.
- **Monkeypatched `_FakeAnthropicClient`:** Already used in `tests/test_main.py` for the `POST /chat` SSE test. Replicate for refusal smoke tests.
- **Live-test gating:** `db_conn` fixture skips if Postgres unreachable (Phase 2 pattern). Gate the live Anthropic refusal test on `ANTHROPIC_API_KEY` being set.
- **No f-string SQL:** Static grep guard in test files (present in `test_writer.py`, `test_retrieval.py`, `test_main.py`). Add to eval scorer if it touches DB directly.
- **`asyncio.run()`** for async helper calls in tests (Phase 3 pattern — used in `test_generation.py`).

### Integration Points
- `eval/runs.jsonl` — new append-only log file; created on first run if absent. Scorer reads last line for diff; eval scripts write to it after each run.
- `python -m app.eval.retrieval` and `python -m app.eval.ragas` — new CLI entry points. Follow the `python -m app.ingest.pipeline` entry-point pattern from Phase 1.
- `tests/test_eval_retrieval.py`, `tests/test_eval_ragas.py`, `tests/test_eval_refusal.py` — new test files. Pattern: offline unit tests + live-gated integration tests.

</code_context>

<specifics>
## Specific Ideas

- CLI diff format exactly: `recall@8: 0.60 → 0.80 (+0.20 ↑)  MRR: 0.45 → 0.52 (+0.07 ↑)` — arrow + signed delta + direction glyph per metric
- Refusal phrase check: assert `"I don't have material"` or `"the closest I have"` in response text (both are the exact phrases from `SYSTEM_PROMPT_TEXT` rule 2)
- Adversarial mismatch: use lo-fi tone chunks for an EVH gain query (or similar cross-topic pairing from the existing corpus)
- RAGAS claim decomposer: two sequential `anthropic` client calls per sample — extract claims, then check support

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 5-Evaluation Harness & Grounding Quality*
*Context gathered: 2026-05-27*
