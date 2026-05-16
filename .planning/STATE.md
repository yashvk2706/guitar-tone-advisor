---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: ready_to_execute
last_updated: "2026-05-16T18:50:00.000Z"
progress:
  total_phases: 5
  completed_phases: 0
  total_plans: 5
  completed_plans: 3
  percent: 60
---

# State: Guitar Tone Advisor

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-15)

**Core value:** Given a user's gear and a target tone, produce concrete, cited settings recommendations they can immediately act on.
**Current focus:** Phase 1 — Schema, Forum Ingestion & Golden Eval Set

## Phase Progress

| Phase | Name | Status |
|-------|------|--------|
| 1 | Schema, Forum Ingestion & Golden Eval Set | In Progress (3/5 plans complete) |
| 2 | Retrieval Layer & Gear Aliases | Not Started |
| 3 | Grounded Generation & Minimal Chat UI | Not Started |
| 4 | UI Polish — Knobs, Markdown, Follow-ups | Not Started |
| 5 | Evaluation Harness & Grounding Quality | Not Started |

## Active Context

Phase 1 planned 2026-05-15. 5 plans across 5 waves (sequential data-pipeline dependency chain). SKELETON.md records architectural decisions (Python 3.12, FastAPI 0.136, psycopg3 3.3.4, pgvector 0.4.2, OpenAI 2.36, documents/chunks/ingest_runs schema, Embedder Protocol, eval JSONL schema). Plan 05 requires human checkpoint (interactive eval authoring).

**Plan 01 complete (2026-05-16):** project scaffold + Postgres/pgvector schema shipped (commits 87d1ae2, 766f22d, 087c0e3). INGEST-04 / INGEST-05 marked complete. Verification of `psql -f init_db.sql` + `pytest tests/test_schema.py` deferred to user's local Postgres + Python 3.12 venv.

**Plan 02 complete (2026-05-16):** forum loader + paragraph-packing chunker shipped (commits 604c867 RED, 0516c17 GREEN, cb0dd38 RED, a4cb700 GREEN). `app/ingest/loader.py` returns 10 RawDocuments with NFKC-normalized text and sha256 content_hash; `app/ingest/chunker.py` produces 21 deterministic Chunks (token range 53–494, mean 375) with source-type dispatch and forward-merge of sub-40-word paragraphs. 24/24 pytest cases pass. Two algorithmic bugs caught and fixed before commit: (1) un-accounted `\n\n` separator token cost caused 501-token chunks; (2) inline forward-merge "pending debt" flag chained indefinitely on Q&A threads of short replies, redesigned as a post-pass.

**Plan 03 complete (2026-05-16):** Embedder Protocol + OpenAI implementation + factory shipped (commits 5c8b171 RED, ff56d65 GREEN, 015d547 Task 2). `app/embeddings/base.py` defines runtime-checkable `Embedder` Protocol with separate `embed_documents`/`embed_query` methods and frozen `EmbeddingResult` dataclass. `app/embeddings/openai_embedder.py` wraps `embeddings.create` with `tenacity` retry (stop_after_attempt=5, wait_exponential 1-30s), batches inputs in groups of 64, and pins `_DIMS = {text-embedding-3-small: 1536, text-embedding-3-large: 3072}`. `app/embeddings/factory.py` dispatches on `EMBEDDING_MODEL` prefix — `text-embedding-3-*` → OpenAI; `voyage-*`/`local:` → `NotImplementedError` (Phase 2 drop-in target); unknown → `ValueError`. 16/16 tests pass, 0 `openai` import leaks outside the allowed module (regression test enforces). Two SDK-version deviations auto-fixed: (1) shipped minimal OpenAIEmbedder constructor in Task 1 to satisfy Task 1's factory tests; (2) OpenAI 2.36 enforces credentials at construction so we pass `api_key=` from Settings with offline-safe placeholder fallback. INGEST-03 satisfied. Next: plan 01-04 (idempotent writer + ingestion CLI).

## Decisions

- [Phase 1 Plan 01]: Project scaffold + Postgres/pgvector schema committed (commits 87d1ae2, 766f22d GREEN-test, 087c0e3). INGEST-04 / INGEST-05 marked complete. Settings.database_url gained a local default (`postgresql://localhost:5432/guitar_tone_advisor`) so the plan's own no-env smoke import succeeds without forcing the user to set `DATABASE_URL` first (Rule 3 fix; full rationale in 01-01-SUMMARY.md).
- [Phase 1 Plan 02]: Forum loader (Path.resolve() + sorted glob *.txt + NFKC + sha256) and paragraph-packing chunker (cl100k_base tokens, 500-token hard cap, sub-40-word forward-merge as POST-PASS not inline) committed. Account for 1-token `\n\n` separator overhead in the greedy accumulator. 21 chunks emitted from the 10-file Phase 1 corpus — locked input for Plan 03 embedding + Plan 04 idempotent writer.
- [Phase 1 Plan 03]: Embedder Protocol locked with two distinct methods (`embed_documents`/`embed_query`), frozen `EmbeddingResult` dataclass, factory dispatch on `EMBEDDING_MODEL` prefix. OpenAI 2.36 SDK call shape is `client.embeddings.create(model=..., input=[...])` returning `resp.data[i].embedding` — Plan 04 writer and Phase 2 retrieval rely on this exact shape. Batch size 64 (`BATCH_SIZE` constant). Tenacity retry policy: `stop_after_attempt(5)` + `wait_exponential(min=1, max=30)`. Test-time backoff neutralization pattern: `embedder.embed_documents.retry.wait = wait_fixed(0)` — adopted as the convention for all future tenacity-decorated tests. `OPENAI_API_KEY` passed explicitly to `OpenAI(api_key=...)` from Settings (with offline placeholder fallback) because openai 2.x enforces credentials at construction unlike 0.x/1.x. Regression test `test_no_module_imports_openai_outside_openai_embedder` greps the `app/` tree to prevent future abstraction leaks (CLAUDE.md hard constraint T-03-01).
