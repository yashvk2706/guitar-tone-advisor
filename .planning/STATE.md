---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: ready_to_execute
last_updated: "2026-05-16T19:00:00.000Z"
progress:
  total_phases: 5
  completed_phases: 0
  total_plans: 5
  completed_plans: 2
  percent: 40
---

# State: Guitar Tone Advisor

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-15)

**Core value:** Given a user's gear and a target tone, produce concrete, cited settings recommendations they can immediately act on.
**Current focus:** Phase 1 — Schema, Forum Ingestion & Golden Eval Set

## Phase Progress

| Phase | Name | Status |
|-------|------|--------|
| 1 | Schema, Forum Ingestion & Golden Eval Set | In Progress (2/5 plans complete) |
| 2 | Retrieval Layer & Gear Aliases | Not Started |
| 3 | Grounded Generation & Minimal Chat UI | Not Started |
| 4 | UI Polish — Knobs, Markdown, Follow-ups | Not Started |
| 5 | Evaluation Harness & Grounding Quality | Not Started |

## Active Context

Phase 1 planned 2026-05-15. 5 plans across 5 waves (sequential data-pipeline dependency chain). SKELETON.md records architectural decisions (Python 3.12, FastAPI 0.136, psycopg3 3.3.4, pgvector 0.4.2, OpenAI 2.36, documents/chunks/ingest_runs schema, Embedder Protocol, eval JSONL schema). Plan 05 requires human checkpoint (interactive eval authoring).

**Plan 01 complete (2026-05-16):** project scaffold + Postgres/pgvector schema shipped (commits 87d1ae2, 766f22d, 087c0e3). INGEST-04 / INGEST-05 marked complete. Verification of `psql -f init_db.sql` + `pytest tests/test_schema.py` deferred to user's local Postgres + Python 3.12 venv.

**Plan 02 complete (2026-05-16):** forum loader + paragraph-packing chunker shipped (commits 604c867 RED, 0516c17 GREEN, cb0dd38 RED, a4cb700 GREEN). `app/ingest/loader.py` returns 10 RawDocuments with NFKC-normalized text and sha256 content_hash; `app/ingest/chunker.py` produces 21 deterministic Chunks (token range 53–494, mean 375) with source-type dispatch and forward-merge of sub-40-word paragraphs. 24/24 pytest cases pass. Two algorithmic bugs caught and fixed before commit: (1) un-accounted `\n\n` separator token cost caused 501-token chunks; (2) inline forward-merge "pending debt" flag chained indefinitely on Q&A threads of short replies, redesigned as a post-pass. Next: plan 01-03 (Embedder Protocol + OpenAI implementation).

## Decisions

- [Phase 1 Plan 01]: Project scaffold + Postgres/pgvector schema committed (commits 87d1ae2, 766f22d GREEN-test, 087c0e3). INGEST-04 / INGEST-05 marked complete. Settings.database_url gained a local default (`postgresql://localhost:5432/guitar_tone_advisor`) so the plan's own no-env smoke import succeeds without forcing the user to set `DATABASE_URL` first (Rule 3 fix; full rationale in 01-01-SUMMARY.md).
- [Phase 1 Plan 02]: Forum loader (Path.resolve() + sorted glob *.txt + NFKC + sha256) and paragraph-packing chunker (cl100k_base tokens, 500-token hard cap, sub-40-word forward-merge as POST-PASS not inline) committed. Account for 1-token `\n\n` separator overhead in the greedy accumulator. 21 chunks emitted from the 10-file Phase 1 corpus — locked input for Plan 03 embedding + Plan 04 idempotent writer.
