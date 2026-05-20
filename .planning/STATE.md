---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: In progress
stopped_at: Phase 3 Plan 03 complete. Resume at 03-04-PLAN.md.
last_updated: "2026-05-20T18:32:00.000Z"
progress:
  total_phases: 5
  completed_phases: 2
  total_plans: 12
  completed_plans: 11
  percent: 58
---

# State: Guitar Tone Advisor

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-15)

**Core value:** Given a user's gear and a target tone, produce concrete, cited settings recommendations they can immediately act on.
**Current focus:** Phase 3 — Grounded Generation & Minimal Chat UI

## Phase Progress

| Phase | Name | Status |
|-------|------|--------|
| 1 | Schema, Forum Ingestion & Golden Eval Set | Complete (5/5 plans) |
| 2 | Retrieval Layer & Gear Aliases | Complete (3/3 plans) |
| 3 | Grounded Generation & Minimal Chat UI | In Progress (3/4 executed) |
| 4 | UI Polish — Knobs, Markdown, Follow-ups | Not Started |
| 5 | Evaluation Harness & Grounding Quality | Not Started |

## Active Context

**Phase 1 complete (2026-05-19).** All 5 plans shipped. 21 chunks from 10 forum posts embedded and stored in Postgres (pgvector/pg17 via Docker). Golden eval set authored and committed: `eval/golden_set.jsonl` (22 tuples) + `eval/HELD_OUT.md` (5 held-out tuples from 5 distinct topics: bb_king, eddie_van_halen, funk, lo_fi, mark_knopfler). D-11 audit statement locked at 2026-05-19T00:54:58+00:00. Infrastructure: Python 3.12 venv at `venv/`, Docker Compose at `docker-compose.yml` (pgvector/pgvector:pg17), `.env` with DATABASE_URL + OPENAI_API_KEY.

**Phase 2 Plan 01 complete (2026-05-19).** data/gear_aliases.json (14 corpus-verified alias pairs) + app/retrieval/__init__.py + app/retrieval/aliases.py (expand_query bidirectional word-boundary regex, lru_cache) + app/retrieval/base.py (ChunkResult frozen dataclass, retrieve() HNSW function) committed. 19/19 tests pass (17 offline + 2 live-DB). INGEST-07 satisfied. Key fixes: skip-on-shortform-match to prevent double-expansion; Vector() wrapper for pgvector SELECT <=> params (list[float] alone produces double precision[] which fails operator lookup).

**Phase 2 Plan 02 complete (2026-05-19).** app/retrieval/base.py verified: all 7 plan verification tests pass. Settings.debug field added (debug: bool = False). EXPLAIN ANALYZE debug logging added to retrieve() (gated on settings.debug). test_no_fstring_sql alias added to tests/test_retrieval.py. 97/97 offline tests pass (5 live-DB skipped). RETR-01, RETR-02, RETR-03 satisfied.

**Phase 2 Plan 03 complete (2026-05-19).** tests/test_retrieval.py finalized: import dataclasses added; test_chunk_result_is_frozen updated to use dataclasses.FrozenInstanceError (plan success criteria); test_chunk_result_fields updated to assert field names via dataclasses.fields(). 18 offline tests pass, 2 live-DB tests skip gracefully. Full suite: 97 passed, 5 skipped. Phase 2 complete — all 3/3 plans shipped. INGEST-07, RETR-01, RETR-02, RETR-03 satisfied.

**Phase 3 Plan 01 complete (2026-05-20).** app/generation/ package created: __init__.py (empty), prompt.py (SYSTEM_PROMPT_TEXT + 3 D-13 grounding rules, build_system_blocks with cache_control ephemeral, build_sources_xml, build_messages), generator.py (stream_response async generator with _CITATION_RE module-level regex, session→tokens→citations SSE sequence, post-stream citation validation). app/config.py: anthropic_api_key field added. tests/test_generation.py: 9 offline unit tests, TDD RED→GREEN cycle. Full suite: 119 passed, 5 skipped. GEN-01 through GEN-07, CITE-02, CITE-03 implementation foundation complete.

**Phase 3 Plan 02 complete (2026-05-20).** app/session.py created: module-level _sessions dict, threading.Lock() guard (T-03-06 mitigation), MAX_MESSAGES=20 (10 turn pairs per D-12), get_or_create_session() creates-if-absent returning live list view, append_turn() with del turns[:2] sliding window. tests/test_session.py: 3 offline unit tests with exact names from 03-VALIDATION.md. TDD RED→GREEN cycle confirmed. Full suite: 122 passed, 5 skipped. CHAT-02 implementation complete.

**Phase 3 Plan 03 complete (2026-05-20).** app/main.py created: FastAPI app with GET /health ({"status": "ok"}), POST /chat (SSE streaming, gear injection, session resolution, EventSourceResponse with ping=0), GET /sources/{chunk_id} (_SOURCES_SQL with %s::uuid, per-request get_conn(), source_name from metadata_json). tests/test_main.py: 3 tests (test_chat_endpoint_returns_event_stream with monkeypatch, test_get_source_returns_chunk_text live-DB gated, test_no_fstring_sql_in_main static scan). TDD RED→GREEN cycle confirmed. Full suite: 126 passed, 4 skipped. GEN-07, CHAT-01, CHAT-02, CITE-01 wired into HTTP layer.

## Decisions

- [Phase 1 Plan 01]: Project scaffold + Postgres/pgvector schema committed (commits 87d1ae2, 766f22d GREEN-test, 087c0e3). INGEST-04 / INGEST-05 marked complete. Settings.database_url gained a local default (`postgresql://localhost:5432/guitar_tone_advisor`) so the plan's own no-env smoke import succeeds without forcing the user to set `DATABASE_URL` first (Rule 3 fix; full rationale in 01-01-SUMMARY.md).
- [Phase 1 Plan 02]: Forum loader (Path.resolve() + sorted glob *.txt + NFKC + sha256) and paragraph-packing chunker (cl100k_base tokens, 500-token hard cap, sub-40-word forward-merge as POST-PASS not inline) committed. Account for 1-token `\n\n` separator overhead in the greedy accumulator. 21 chunks emitted from the 10-file Phase 1 corpus — locked input for Plan 03 embedding + Plan 04 idempotent writer.
- [Phase 1 Plan 03]: Embedder Protocol locked with two distinct methods (`embed_documents`/`embed_query`), frozen `EmbeddingResult` dataclass, factory dispatch on `EMBEDDING_MODEL` prefix. OpenAI 2.36 SDK call shape is `client.embeddings.create(model=..., input=[...])` returning `resp.data[i].embedding` — Plan 04 writer and Phase 2 retrieval rely on this exact shape. Batch size 64 (`BATCH_SIZE` constant). Tenacity retry policy: `stop_after_attempt(5)` + `wait_exponential(min=1, max=30)`. Test-time backoff neutralization pattern: `embedder.embed_documents.retry.wait = wait_fixed(0)` — adopted as the convention for all future tenacity-decorated tests. `OPENAI_API_KEY` passed explicitly to `OpenAI(api_key=...)` from Settings (with offline placeholder fallback) because openai 2.x enforces credentials at construction unlike 0.x/1.x. Regression test `test_no_module_imports_openai_outside_openai_embedder` greps the `app/` tree to prevent future abstraction leaks (CLAUDE.md hard constraint T-03-01).
- [Phase 1 Plan 04]: Two-phase dedup pattern locked — application-level `chunks_to_embed` partition (avoids embedding API calls; the cost-saver) AND db-level `ON CONFLICT (document_id, chunk_index, embedding_model) DO UPDATE` safety net (catches partition slip). Vectors flow as `list[float]` through the pgvector adapter; defensive `assert(len(chunks)==len(vectors))` at the top of `upsert_chunks` prevents silent vector misattribution (T-04-02). Per-document `conn.commit()` for partial durability — a mid-run crash leaves a valid prefix of the corpus, not an all-or-nothing rollback. `fail_run` writes through a FRESH connection so the audit row survives the main-tx rollback (T-04-08). `repr(e)` not `traceback.format_exc()` to avoid leaking SDK request bodies into the audit row (T-04-05). `ingest_runs` is NOT truncated on `--full-rebuild` — the audit trail of every prior run survives across full-rebuilds so the operator can compare counters across re-embeds. `_PHASE_1_SOURCE_TYPE = "forum"` is hard-coded in `upsert_chunks`; Phase 2 will pass `source_type` through from `RawDocument` when PDF/web/youtube chunkers come online. Embedder construction happens BEFORE `get_conn()` so a factory error fails the process before touching the DB. Static no-f-string-SQL grep is in `tests/test_writer.py::test_no_fstring_sql_in_writer` and runs without infra (T-04-01 mitigation). Pipeline `--help` test gates argparse wiring on a path that needs neither DB nor API key. INGEST-01 / INGEST-02 / INGEST-06 marked complete.
- [Phase 1 Plan 05]: Golden eval set authored and committed. 22 GoldenTuples in `eval/golden_set.jsonl`, 5 held-out (indices 0, 2, 4, 8, 11) from bb_king_tone, eddie_van_halen_tone, funk_tone, lo_fi_tone, mark_knopfler_bowed_sound. `eval/HELD_OUT.md` locked at 2026-05-19T00:54:58+00:00 with D-11 audit statement. `app/eval/author.py` gained `--full-text` flag post-plan for reviewer convenience. EVAL-01 satisfied.
- [Infrastructure]: Docker Compose (`docker-compose.yml`) added with `pgvector/pgvector:pg17` image. Python 3.12 venv at `venv/`. DATABASE_URL uses `postgres:postgres` credentials for local Docker instance.
- [Phase 2 Plan 01]: data/gear_aliases.json (14 corpus-verified pairs: Strat/Tele/EVH/SLO/5150/6505/AX8/SD1/GE-7/HM-2/Dual Rec/Maxon 808/SRV/SSS). app/retrieval/aliases.py: skip-on-shortform-match pattern prevents double-expansion (Pitfall 3 fix — PATTERNS.md ran both re.sub rules unconditionally). app/retrieval/base.py: Vector() wrapper required for pgvector SELECT <=> params — VectorDumper only registered for Vector/numpy.ndarray, not plain list[float]; INSERT works without it (column type provides cast context) but SELECT does not. Test runner must use venv/bin/python (system anaconda lacks psycopg/pgvector). INGEST-07 complete.
- [Phase 2 Plan 02]: Settings.debug: bool = False added to app/config.py (plan done criteria). EXPLAIN ANALYZE debug logging wired into retrieve() — gated on settings.debug, prints plan rows to stdout. test_no_fstring_sql = test_no_fstring_sql_in_base alias added to tests/test_retrieval.py so plan's exact pytest verification command resolves. 7/7 plan verification tests pass. RETR-01, RETR-02, RETR-03 complete.
- [Phase 2 Plan 03]: tests/test_retrieval.py finalized for plan 03 success criteria: import dataclasses added; test_chunk_result_is_frozen uses dataclasses.FrozenInstanceError (not (AttributeError, TypeError)); test_chunk_result_fields asserts exact 7-field set via dataclasses.fields(). Extra coverage tests from Plans 01/02 kept (case-insensitive expansion, count-one, no-match, empty-pairs, load-14-tuples, source-name mapping). Phase 2 complete.
- [Phase 3 Plan 01]: SYSTEM_PROMPT_TEXT uses lowercase "cite it inline as [Sn]" (lowercase c) in grounding rule 1 to match the exact phrase the test_system_prompt_contains_grounding_rules test asserts from the D-13 requirement. asyncio.run() used for async test helpers (replaces deprecated asyncio.get_event_loop().run_until_complete() — Python 3.12 deprecation). build_sources_xml([]) returns "<sources>\n</sources>" two-line form for empty sources (signals corpus-silent refusal path to model). stream_response() is an async generator — all injectable dependencies are keyword-only; client= is required (no default) so tests must supply _FakeAnthropicClient explicitly (no get_anthropic_client() factory yet).
- [Phase 3 Plan 02]: app/session.py uses a module-level dict + threading.Lock() (no nested lock acquisition). del turns[:2] always drops exactly 2 messages to preserve role alternation per D-12. get_or_create_session() returns a view into the live list (not a copy) — callers see appended turns without re-fetching. Test isolation via autouse _reset_sessions fixture (mirrors _reset_alias_cache pattern from test_retrieval.py). CHAT-02 complete.
- [Phase 3 Plan 03]: per-request AsyncAnthropic client (never module-level) constructed inside route handler with HTTPException(500) if api_key is None. EventSourceResponse(event_gen(), ping=0) — ping=0 prevents sse-starlette ping comments causing frontend JSON.parse errors (Pitfall 2). User turn appended before EventSourceResponse; assistant turn appended inside event_gen() after stream_response exhausts. GET /sources/{chunk_id}: try/except around cur.execute to catch Postgres DataError on invalid UUID cast → 404. Monkeypatch-based TestClient test for SSE endpoint (no pytest-asyncio). GEN-07, CHAT-01, CITE-01 complete.

## Session Continuity

Last session: 2026-05-20
Stopped at: Phase 3 Plan 03 complete. FastAPI app committed.
Resume file: .planning/phases/03-grounded-generation-minimal-chat-ui/03-04-PLAN.md
