---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: ready_to_plan
last_updated: "2026-05-19T00:00:00.000Z"
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 5
  completed_plans: 5
  percent: 100
---

# State: Guitar Tone Advisor

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-15)

**Core value:** Given a user's gear and a target tone, produce concrete, cited settings recommendations they can immediately act on.
**Current focus:** Phase 2 — Retrieval Layer & Gear Aliases

## Phase Progress

| Phase | Name | Status |
|-------|------|--------|
| 1 | Schema, Forum Ingestion & Golden Eval Set | Complete (5/5 plans) |
| 2 | Retrieval Layer & Gear Aliases | Not Started |
| 3 | Grounded Generation & Minimal Chat UI | Not Started |
| 4 | UI Polish — Knobs, Markdown, Follow-ups | Not Started |
| 5 | Evaluation Harness & Grounding Quality | Not Started |

## Active Context

**Phase 1 complete (2026-05-19).** All 5 plans shipped. 21 chunks from 10 forum posts embedded and stored in Postgres (pgvector/pg17 via Docker). Golden eval set authored and committed: `eval/golden_set.jsonl` (22 tuples) + `eval/HELD_OUT.md` (5 held-out tuples from 5 distinct topics: bb_king, eddie_van_halen, funk, lo_fi, mark_knopfler). D-11 audit statement locked at 2026-05-19T00:54:58+00:00. Infrastructure: Python 3.12 venv at `venv/`, Docker Compose at `docker-compose.yml` (pgvector/pgvector:pg17), `.env` with DATABASE_URL + OPENAI_API_KEY.

**Phase 2 ready to plan.** Dependencies satisfied: chunks in DB, golden eval set locked, HELD_OUT.md committed before any retrieval tuning.

## Decisions

- [Phase 1 Plan 01]: Project scaffold + Postgres/pgvector schema committed (commits 87d1ae2, 766f22d GREEN-test, 087c0e3). INGEST-04 / INGEST-05 marked complete. Settings.database_url gained a local default (`postgresql://localhost:5432/guitar_tone_advisor`) so the plan's own no-env smoke import succeeds without forcing the user to set `DATABASE_URL` first (Rule 3 fix; full rationale in 01-01-SUMMARY.md).
- [Phase 1 Plan 02]: Forum loader (Path.resolve() + sorted glob *.txt + NFKC + sha256) and paragraph-packing chunker (cl100k_base tokens, 500-token hard cap, sub-40-word forward-merge as POST-PASS not inline) committed. Account for 1-token `\n\n` separator overhead in the greedy accumulator. 21 chunks emitted from the 10-file Phase 1 corpus — locked input for Plan 03 embedding + Plan 04 idempotent writer.
- [Phase 1 Plan 03]: Embedder Protocol locked with two distinct methods (`embed_documents`/`embed_query`), frozen `EmbeddingResult` dataclass, factory dispatch on `EMBEDDING_MODEL` prefix. OpenAI 2.36 SDK call shape is `client.embeddings.create(model=..., input=[...])` returning `resp.data[i].embedding` — Plan 04 writer and Phase 2 retrieval rely on this exact shape. Batch size 64 (`BATCH_SIZE` constant). Tenacity retry policy: `stop_after_attempt(5)` + `wait_exponential(min=1, max=30)`. Test-time backoff neutralization pattern: `embedder.embed_documents.retry.wait = wait_fixed(0)` — adopted as the convention for all future tenacity-decorated tests. `OPENAI_API_KEY` passed explicitly to `OpenAI(api_key=...)` from Settings (with offline placeholder fallback) because openai 2.x enforces credentials at construction unlike 0.x/1.x. Regression test `test_no_module_imports_openai_outside_openai_embedder` greps the `app/` tree to prevent future abstraction leaks (CLAUDE.md hard constraint T-03-01).
- [Phase 1 Plan 04]: Two-phase dedup pattern locked — application-level `chunks_to_embed` partition (avoids embedding API calls; the cost-saver) AND db-level `ON CONFLICT (document_id, chunk_index, embedding_model) DO UPDATE` safety net (catches partition slip). Vectors flow as `list[float]` through the pgvector adapter; defensive `assert(len(chunks)==len(vectors))` at the top of `upsert_chunks` prevents silent vector misattribution (T-04-02). Per-document `conn.commit()` for partial durability — a mid-run crash leaves a valid prefix of the corpus, not an all-or-nothing rollback. `fail_run` writes through a FRESH connection so the audit row survives the main-tx rollback (T-04-08). `repr(e)` not `traceback.format_exc()` to avoid leaking SDK request bodies into the audit row (T-04-05). `ingest_runs` is NOT truncated on `--full-rebuild` — the audit trail of every prior run survives across full-rebuilds so the operator can compare counters across re-embeds. `_PHASE_1_SOURCE_TYPE = "forum"` is hard-coded in `upsert_chunks`; Phase 2 will pass `source_type` through from `RawDocument` when PDF/web/youtube chunkers come online. Embedder construction happens BEFORE `get_conn()` so a factory error fails the process before touching the DB. Static no-f-string-SQL grep is in `tests/test_writer.py::test_no_fstring_sql_in_writer` and runs without infra (T-04-01 mitigation). Pipeline `--help` test gates argparse wiring on a path that needs neither DB nor API key. INGEST-01 / INGEST-02 / INGEST-06 marked complete.
- [Phase 1 Plan 05]: Golden eval set authored and committed. 22 GoldenTuples in `eval/golden_set.jsonl`, 5 held-out (indices 0, 2, 4, 8, 11) from bb_king_tone, eddie_van_halen_tone, funk_tone, lo_fi_tone, mark_knopfler_bowed_sound. `eval/HELD_OUT.md` locked at 2026-05-19T00:54:58+00:00 with D-11 audit statement. `app/eval/author.py` gained `--full-text` flag post-plan for reviewer convenience. EVAL-01 satisfied.
- [Infrastructure]: Docker Compose (`docker-compose.yml`) added with `pgvector/pgvector:pg17` image. Python 3.12 venv at `venv/`. DATABASE_URL uses `postgres:postgres` credentials for local Docker instance.

## Session Continuity

Last session: 2026-05-19
Stopped at: Phase 1 complete. Ready to plan Phase 2.
Resume file: none
