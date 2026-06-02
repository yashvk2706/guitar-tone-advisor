# Roadmap: Guitar Tone Advisor

**Created:** 2026-05-15
**Last updated:** 2026-05-29 (Phase 6 planned — 5 plans across 4 waves)
**Granularity:** Standard
**Project mode:** Vertical MVP — each phase ships an end-to-end working slice (or the smallest verifiable deliverable thereof)
**Coverage:** 33/33 v1 requirements mapped (100%)

## Phases

- [x] **Phase 1: Schema, Forum Ingestion & Golden Eval Set** — Migrate Postgres + pgvector, build forum-only CLI ingestion pipeline, and author the held-out golden eval set before any retrieval tuning
- [x] **Phase 2: Retrieval Layer & Gear Aliases** — Wire HNSW cosine retrieval through the Embedder Protocol with bidirectional gear-alias query expansion
- [x] **Phase 3: Grounded Generation & Minimal Chat UI** — End-to-end SSE-streamed answers with inline `[S{n}]` citations rendered in a minimal Next.js chat
- [x] **Phase 4: UI Polish — Knobs, Markdown, Follow-ups** — Add rotary-knob settings, Markdown rendering, follow-up buttons, copy-to-clipboard, loading states, session history
- [x] **Phase 5: Evaluation Harness & Grounding Quality** — Score against the existing golden eval set (recall@K / MRR), empty-context refusal smoke test, RAGAS faithfulness
- [ ] **Phase 6: Full Corpus Ingestion** — Extend the ingest pipeline to handle PDF manuals, YouTube transcripts, and web articles; run the full pipeline and verify eval scores improve
- [ ] **Phase 7: Persistent Corpus & Cloud Deployment** — Confirm corpus persists without re-ingestion across Docker restarts; deploy app to AWS (EC2 + managed Postgres with pgvector) at a public HTTPS URL with pre-seeded corpus

## Phase Details

### Phase 1: Schema, Forum Ingestion & Golden Eval Set
**Goal:** A guitarist can run one CLI command and have every forum post in `raw_data/forum_posts/` become a chunked, embedded, idempotently-stored row in Postgres ready for retrieval — and a held-out golden eval set exists on disk before anyone tunes a retrieval parameter.
**Mode:** mvp
**Depends on:** Nothing (first phase)
**Requirements:** INGEST-01, INGEST-02, INGEST-03, INGEST-04, INGEST-05, INGEST-06, EVAL-01
**Plans:** 5 plans across 5 sequential waves (W1: 01 schema; W2: 02 chunker; W3: 03 embedder; W4: 04 writer + pipeline; W5: 05 eval authoring). Walking Skeleton; see `.planning/phases/01-schema-forum-ingestion-golden-eval-set/SKELETON.md`.
**Success Criteria** (what must be TRUE):
  1. Running `python -m app.ingest.pipeline` against `raw_data/forum_posts/` populates the `chunks` table with one row per chunk, each row carrying source_type/source_name/chunk_index/content_hash metadata
  2. Every stored chunk has a `vector(1536)` embedding generated via the model named in `EMBEDDING_MODEL` (default `text-embedding-3-small`)
  3. The `chunks` table has a working HNSW index on the embedding column using `vector_cosine_ops` (verified by `EXPLAIN ANALYZE` showing index scan, not seq scan)
  4. Re-running the ingestion CLI on unchanged input re-embeds zero chunks (idempotency via content-hash dedup)
  5. `eval/golden_set.jsonl` contains ≥20 `(query, expected_chunk_ids, expected_themes)` tuples derived from the 10 forum-post topics, with a held-out subset committed *before* any retrieval tuning has been performed (timestamp and held-out manifest recorded in `eval/HELD_OUT.md`)
Plans:
- [x] 01-01-PLAN.md — Postgres + pgvector schema migration: `scripts/init_db.sql`, `documents`/`chunks`/`ingest_runs` tables, HNSW index `chunks_embedding_hnsw_cos` with `m=16, ef_construction=64`, `pg_trgm` pre-installed for Phase 3 headroom; `app/config.py` + `app/db.py` with `register_vector` registered
- [x] 01-02-PLAN.md — Forum-post loader (`app/ingest/loader.py`) and paragraph-packing chunker (`app/ingest/chunker.py`); NFKC normalization, deterministic content hashes, `source_type` dispatch, forward-merge of sub-40-word paragraphs, 300–500 token budget per D-01/D-02
- [x] 01-03-PLAN.md — `Embedder` Protocol (`app/embeddings/base.py`), `OpenAIEmbedder` with tenacity retry and batch-of-64 (`app/embeddings/openai_embedder.py`), factory dispatch on `EMBEDDING_MODEL` (`app/embeddings/factory.py`); `embed_documents`/`embed_query` split per CLAUDE.md hard constraint
- [x] 01-04-PLAN.md — Writer (`app/ingest/writer.py`) with content-hash dedup, `ingest_runs` lifecycle, and CLI pipeline (`app/ingest/pipeline.py`) entry point `python -m app.ingest.pipeline [--full-rebuild]`; satisfies INGEST-01/02/06 idempotency contract
- [x] 01-05-PLAN.md — Golden eval set authoring [EVAL-01]: `app/eval/schema.py` (pydantic `GoldenTuple`, theme enum), `app/eval/author.py` (interactive top-K candidate review CLI per D-07), `eval/QUERIES.md` (≥20 draft queries spanning all 10 forum topics), `eval/golden_set.jsonl`, `eval/HELD_OUT.md` (15/5 split per D-10, ISO-timestamped lock per D-11); checkpoint task for human accept/reject loop

### Phase 2: Retrieval Layer & Gear Aliases
**Goal:** A guitarist's free-text tone query (with gear shortforms like "TS9" or "JCM800") returns the top-K most relevant forum chunks with full source metadata, expanded against a curated gear-alias map before embedding.
**Mode:** mvp
**Depends on:** Phase 1 (chunks must exist in the store and the golden eval set must be locked before tuning K, chunking, or expansion)
**Requirements:** INGEST-07, RETR-01, RETR-02, RETR-03
**Plans:** 3/3 plans complete
**Success Criteria** (what must be TRUE):
  1. A `gear_aliases.json` file exists mapping at least the gear referenced in the existing forum corpus (TS9, JCM800, EVH, Strat, etc.) bidirectionally to canonical names
  2. A query containing a gear shortform retrieves the same top chunks as the same query with the canonical name (verified by spot check on at least 3 alias pairs)
  3. A retrieval call returns the top-K=8 chunks ranked by HNSW cosine similarity, each chunk dict including source_type, source_name, chunk_index/page reference, and raw text
  4. Retrieval-layer unit test asserts `register_vector(conn)` is invoked once per pool connection and queries use the `<=>` cosine operator
Plans:
- [x] 02-01-PLAN.md — `data/gear_aliases.json` (14 corpus-verified pairs) + `app/retrieval/__init__.py` (empty package) + `app/retrieval/aliases.py` (`_load_alias_pairs` with lru_cache, `expand_query` with re.sub word-boundary matching per D-03/D-05); covers INGEST-07
- [x] 02-02-PLAN.md — `app/retrieval/base.py`: `ChunkResult` frozen dataclass (7 fields per D-06), `_RETRIEVE_SQL` constant (<=> cosine, %s params, query_vec twice), `_row_to_chunk_result` (metadata_json['source_filename'] → source_name), `retrieve()` (expand_query → embed_query → cursor.execute → list[ChunkResult]); covers RETR-01, RETR-02, RETR-03
- [x] 02-03-PLAN.md — `tests/test_retrieval.py`: 12 offline unit/static tests + 2 live-DB integration tests (db_conn-gated, skip if Postgres unreachable); _FakeEmbedder + _FakeConn + _FakeCursor helpers; static guards for no-openai-import, no-f-string-SQL, no-register_vector-in-retrieve; covers verification of all 4 Phase 2 requirements

### Phase 3: Grounded Generation & Minimal Chat UI
**Goal:** A guitarist opens the web app, types their gear + a target tone, and watches a streamed, cited recommendation appear — with `[S{n}]` markers that open a drawer showing the actual forum-post text, and a refusal-with-reason whenever the corpus is silent.
**Mode:** mvp
**Depends on:** Phase 2
**Requirements:** GEN-01, GEN-02, GEN-03, GEN-04, GEN-05, GEN-06, GEN-07, CHAT-01, CHAT-02, CHAT-03, CITE-01, CITE-02, CITE-03
**Plans:** 4/4 plans complete
**Success Criteria** (what must be TRUE):
  1. Asking "What amp settings did BB King use?" through the chat UI yields a streamed answer with at least one `[S{n}]` citation; clicking the citation opens a drawer showing the actual forum-post chunk text and a source-type label (`[Forum]`)
  2. The same query asked against an artificially empty retrieval result produces a refusal with a reason (e.g., "I don't have material on …") rather than a fabricated answer
  3. The answer contains concrete knob positions on a 0-10 scale and/or a signal-chain order when the cited chunks contain them; gear-translation phrasing appears when the user's described gear differs from the cited gear
  4. A "New chat" button clears the in-process session memory; subsequent messages have no recollection of prior turns
  5. Each answer renders a corpus-coverage indicator naming how many distinct sources support it (e.g., "3 sources agree")
Plans:
- [x] 03-01-PLAN.md — `app/generation/` package: `prompt.py` (SYSTEM_PROMPT_TEXT, build_system_blocks, build_sources_xml, build_messages), `generator.py` (stream_response async generator, _CITATION_RE, post-stream validator); `app/config.py` + anthropic_api_key field; `tests/test_generation.py` Wave 0 stubs (9 tests); covers GEN-01 through GEN-07, CITE-02, CITE-03
- [x] 03-02-PLAN.md — `app/session.py` (in-process dict, threading.Lock, MAX_MESSAGES=20, get_or_create_session, append_turn with sliding window); `tests/test_session.py` Wave 0 stubs (3 tests); covers CHAT-02, CHAT-03
- [x] 03-03-PLAN.md — `app/main.py` FastAPI app: POST /chat (SSE stream, gear injection, retrieve→generate→session), GET /sources/{chunk_id} (drawer hydration, _SOURCES_SQL, get_conn per-request), GET /health; `tests/test_main.py` Wave 0 stubs (3 tests); covers GEN-07, CHAT-01, CHAT-02, CITE-01
- [x] 03-04-PLAN.md — `frontend/` Next.js App Router (TypeScript + Tailwind + lucide-react): `next.config.js` (/api/py/* rewrites), `hooks/useSSEStream.ts` (ReadableStream SSE parser), `components/ChatPage.tsx` (orchestration + state), `components/MessageBubble.tsx`, `components/CitationPill.tsx`, `components/CitationDrawer.tsx`, `components/CoverageIndicator.tsx`; human checkpoint; covers CHAT-01, CHAT-03, CITE-01, CITE-02, CITE-03
**UI hint**: yes

### Phase 4: UI Polish — Knobs, Markdown, Follow-ups
**Goal:** The chat UI graduates from minimal-but-functional to actually-pleasant: Markdown formatting, visual rotary-knob renderings of knob settings, scrollable session history, one-click copy of the recommendation block, loading-state messaging, and three suggested follow-up action buttons under every answer.
**Mode:** mvp
**Depends on:** Phase 3
**Requirements:** CHAT-04, UI-01, UI-02, UI-03, UI-04, UI-05
**Plans:** 4 plans across 3 waves
**Success Criteria** (what must be TRUE):
  1. Markdown in the model's output (bold, bulleted lists, fenced code) renders correctly in the browser
  2. When the answer contains knob settings (e.g., "Bass=7, Mid=4, Treble=6"), each setting renders as a visual rotary-knob component turned to the correct position with the numeric value labeled beneath
  3. The full session's prior turns remain visible and scrollable above the current input
  4. A single "Copy" button on each recommendation block copies the amp/pedal settings to the system clipboard
  5. While a response is generating, the UI shows a labeled progress indicator that transitions ("Searching corpus..." → "Drafting...")
  6. Three suggested follow-up buttons ("Cleaner?", "Live setting?", "Budget version?") appear under each answer and, when clicked, submit the corresponding follow-up turn
Plans:
- [x] 04-01-PLAN.md — react-markdown@10.1.0 install + MARKDOWN_COMPONENTS wired into MessageBubble; streaming cursor moved to outer bubble wrapper; npm run build passes [W1; UI-01, UI-02]
- [x] 04-02-PLAN.md — parseKnobs.ts (regex extractor, last-value-wins, 0–10 range filter) + RotaryKnob.tsx (inline SVG, 270° arc, zinc colors) + knob row in MessageBubble behind D-08 post-stream gate [W2; UI-05]
- [x] 04-03-PLAN.md — streamPhase state machine in ChatPage (idle→searching→drafting→idle) + loadingLabel prop to MessageBubble + copy button (opacity-0 group-hover, navigator.clipboard, 2s Check feedback) [W2; UI-02, UI-03, UI-04]
- [x] 04-04-PLAN.md — FollowUpRail.tsx (three fixed buttons) + isLatestAssistant + onFollowUp wired through MessageBubble and ChatPage; final npm run build [W3; CHAT-04]
**UI hint**: yes

### Phase 5: Evaluation Harness & Grounding Quality
**Goal:** Every future retrieval or prompt change can be judged against the held-out golden eval set authored in Phase 1 and a faithfulness score — no more vibes-based tuning, and the empty-context refusal contract is enforced by an automated smoke test.
**Mode:** mvp
**Depends on:** Phase 1 (golden eval set must already exist on disk); Phase 2 (retrieval must exist before recall@K is meaningful); Phase 3 (generation must exist before refusal/faithfulness can be measured)
**Requirements:** EVAL-02, EVAL-03, EVAL-04
**Success Criteria** (what must be TRUE):
  1. Running `python -m app.eval.retrieval` loads the existing `eval/golden_set.jsonl` (authored in Phase 1), prints recall@K and MRR, and appends the numbers to `eval/runs.jsonl` after each retrieval configuration change
  2. An automated smoke test passes when, given `retrieved_chunks=[]`, the generation layer returns a refusal (no fabricated knob settings, no hallucinated gear names)
  3. Running `python -m app.eval.ragas` on a sample of generated answers prints a faithfulness score and logs per-claim support evidence
**Plans:** 3 plans across 3 sequential waves
Plans:
**Wave 1**
- [x] 05-01-PLAN.md — Retrieval scorer CLI `python -m app.eval.retrieval`: recall@1/5/8 + MRR (any-hit) against `eval/golden_set.jsonl`, append-only `eval/runs.jsonl`, diff vs previous run [W1; EVAL-02]
**Wave 2** *(blocked on Wave 1 completion)*
- [x] 05-02-PLAN.md — Empty-context + adversarial-mismatch refusal smoke tests in `tests/test_eval_refusal.py`, testing `stream_response()` directly (3 offline + 1 live-gated) [W2; EVAL-03]
**Wave 3** *(blocked on Wave 2 completion)*
- [x] 05-03-PLAN.md — Custom RAGAS faithfulness CLI `python -m app.eval.ragas`: two-step anthropic claim decomposer, `eval/faithfulness_runs.jsonl` log [W3; EVAL-04]

Cross-cutting constraints:
- All eval modules must use `get_embedder()` — never import `openai` directly (CLAUDE.md Embedder Protocol)
- Wave 0 test stubs (failing) must be committed before each plan's implementation task runs

### Phase 6: Full Corpus Ingestion
**Goal:** Extend the ingest pipeline to handle all three remaining source types — PDF equipment manuals, YouTube transcripts, and web articles — then run the full pipeline against `raw_data/` and verify that eval scores (recall@K, faithfulness) improve meaningfully over the forum-only baseline. The ingest architecture already dispatches on `source_type`; Phase 6 implements the three `NotImplementedError` branches.
**Mode:** mvp
**Depends on:** Phase 5 (eval harness must exist to measure improvement)
**Requirements:** INGEST-08, INGEST-09, INGEST-10, EVAL-05
**Success Criteria** (what must be TRUE):
  1. `python -m app.ingest.pipeline` with no flags ingests all four source types: forum posts, PDF manuals (`raw_data/manuals/` — 15 PDFs), YouTube transcripts (`raw_data/youtube_ids.txt` — 13 IDs), and web articles (`raw_data/article_urls.txt` — 10 URLs); chunk count grows from 21 to ≥200
  2. PDF chunker never splits inside a table; `pymupdf4llm` is used as an escalation path for table-heavy pages (CLAUDE.md hard constraint)
  3. YouTube loader uses `youtube-transcript-api` with `yt-dlp` as fallback; transcripts are chunked into 300–500-token windows
  4. Article scraper uses `trafilatura`; boilerplate (nav, ads, footers) is stripped before chunking
  5. Re-running the pipeline on unchanged input embeds zero new chunks (content-hash dedup still holds across all source types)
  6. After full ingest, `python -m app.eval.retrieval` shows recall@8 ≥ 1.0 and MRR ≥ 0.9 on the held-out set; `python -m app.eval.ragas` shows mean faithfulness ≥ 0.5
**Plans:** 4/5 plans executed

**Wave 1** (unblock: fix writer bug + extend RawDocument)
- [x] 06-01-PLAN.md — Fix `upsert_chunks()` source_type hardcode: remove `_PHASE_1_SOURCE_TYPE = "forum"`, add `source_type: str` parameter, update pipeline.py call site + test_writer.py; add `metadata: dict` field to RawDocument [W1; INGEST-08, INGEST-09, INGEST-10]

**Wave 2** (parallel: PDF and YouTube loaders/chunkers, both depend only on Wave 1)
- [x] 06-02-PLAN.md — `load_pdf_manuals()` (pymupdf4llm primary / pypdf fallback) + `chunk_pdf()` (heading-aware section splits, table-atomic rule, ToC skip heuristic, page_number + section_heading metadata); updated dispatch in `chunk_document()` [W2; INGEST-08]
- [x] 06-03-PLAN.md — `load_youtube_transcripts()` (YouTubeTranscriptApi().fetch() instance API, yt-dlp subprocess fallback, source_type="youtube") + `chunk_youtube()` (greedy 300-500 token windows, start_time from first snippet per D-10, video_id in metadata) [W2; INGEST-10]

**Wave 3** (article loader/chunker, depends on Wave 1; could parallel Wave 2 but uses same files)
- [x] 06-04-PLAN.md — `load_web_articles()` (trafilatura fetch_url + extract, 100-word skip threshold per D-07) + `chunk_article()` (same greedy paragraph-packing as forum, source_filename=URL) [W3; INGEST-09]

**Wave 4** (pipeline orchestration + eval gate, depends on all prior waves)
- [x] 06-05-PLAN.md — Extend `pipeline.py::main()` to call all 4 loaders; add --manuals-dir, --youtube-ids, --article-urls CLI args; end-of-run summaries per D-07; update requirements.txt; human checkpoint: full pipeline run + eval score verification [W4; INGEST-08, INGEST-09, INGEST-10, EVAL-05]

### Phase 7: Persistent Corpus & Cloud Deployment
**Goal:** (1) Confirm the corpus persists across Docker restarts without re-ingestion — `docker-compose.yml` already has a `pgdata` named volume; the key constraint is that `docker-compose down -v` destroys it and must never be used in normal operation (document this clearly). (2) Deploy the full app to AWS using available free credits so others can access it at a public HTTPS URL — containerised FastAPI + Next.js, Postgres + pgvector on AWS (RDS or EC2-hosted Docker), API keys managed via AWS Secrets Manager or EC2 environment, corpus pre-seeded so no manual pipeline run is needed after deploy.
**Mode:** mvp
**Depends on:** Phase 6 (full corpus must be ingested before deployment is meaningful)
**Requirements:** PERSIST-01, DEPLOY-01, DEPLOY-02, DEPLOY-03, DEPLOY-04, DEPLOY-05
**Success Criteria** (what must be TRUE):
  1. `docker-compose up -d` followed by `docker-compose down` (without `-v`) followed by `docker-compose up -d` retains all ingested chunks — no re-ingestion needed; this is documented in a `RUNNING.md` warning block
  2. A `Dockerfile` exists for the FastAPI backend and the Next.js frontend is built and served (or deployed to Vercel); a `docker-compose.prod.yml` wires them together for the AWS target
  3. The app is reachable at a public HTTPS URL (nginx + Let's Encrypt or Caddy); the `/health` endpoint returns `{"status": "ok"}` over HTTPS
  4. API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) are stored as AWS Secrets Manager secrets or EC2 instance env vars — never committed to the repo
  5. The deployed Postgres instance has the full corpus pre-seeded (pg_dump/restore or pipeline run as a one-time deploy step); a fresh user visiting the URL can ask a tone question and receive a cited answer without any manual setup
**Pre-deployment prerequisite:** Fix YouTube transcript ingestion (all 13 videos blocked by YouTube bot detection — `RequestBlocked()` on youtube-transcript-api; yt-dlp fallback needs browser cookies via `--cookies-from-browser chrome`). This must be resolved before deployment so the corpus includes YouTube data.
**Plans:** Not planned yet

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Schema, Forum Ingestion & Golden Eval Set | 5/5 | Complete | 2026-05-19 |
| 2. Retrieval Layer & Gear Aliases | 3/3 | Complete    | 2026-05-19 |
| 3. Grounded Generation & Minimal Chat UI | 4/4 | Complete    | 2026-05-20 |
| 4. UI Polish — Knobs, Markdown, Follow-ups | 4/4 | Complete    | 2026-05-22 |
| 5. Evaluation Harness & Grounding Quality | 3/3 | Complete    | 2026-05-28 |
| 6. Full Corpus Ingestion | 5/5 | Complete | 2026-06-02 |
| 7. Persistent Corpus & Cloud Deployment | 0/? | Not planned | — |

---
*Roadmap created 2026-05-15. Every v1 requirement maps to exactly one phase; coverage is 100%.*
*Revision 2026-05-15: EVAL-01 moved from Phase 5 → Phase 1 (final plan) so the golden eval set is locked before any retrieval tuning. Phase 5 Plan 1 now loads the existing eval set rather than authoring it.*
*Revision 2026-05-15: Phase 1 plan files finalized as `01-01-PLAN.md` through `01-05-PLAN.md`; SKELETON.md (Walking Skeleton) added; wave structure W1→W2→W3 (Plans 03+04 parallel)→W4 documented.*
*Revision 2026-05-19: Phase 2 planned — 3 plans across 3 sequential waves. 02-01 alias file/expansion, 02-02 dense retrieval (ChunkResult + retrieve()), 02-03 test suite + static guards.*
*Revision 2026-05-19: Phase 3 planned — 4 plans across 3 waves. W1: 03-01 (generation module + Wave 0 test stubs) + 03-02 (session memory + test stubs) in parallel; W2: 03-03 (FastAPI app + test stubs); W3: 03-04 (Next.js chat UI + human checkpoint).*
*Revision 2026-05-28: Phase 5 planned — 3 plans across 3 sequential waves. W1: 05-01 (retrieval recall scorer + runs.jsonl); W2: 05-02 (refusal smoke tests); W3: 05-03 (custom RAGAS faithfulness CLI). All 3 requirements covered: EVAL-02, EVAL-03, EVAL-04. Each plan leads with a Wave 0 failing-test stub task (RED) before implementation.*
*Revision 2026-05-21: Phase 4 planned — 4 plans across 3 waves. W1: 04-01 (react-markdown); W2: 04-02 (rotary knobs) + 04-03 (loading state + copy button) in parallel; W3: 04-04 (follow-up rail). All 6 requirements covered: CHAT-04, UI-01 through UI-05.*
*Revision 2026-05-29: Phase 6 added — Full Corpus Ingestion (PDF manuals, YouTube transcripts, web articles; eval score improvement gate). Phase 7 added — Persistent Corpus & Cloud Deployment (Docker volume persistence documentation + AWS EC2 deployment with pre-seeded corpus at public HTTPS URL).*
*Revision 2026-05-29: Phase 6 planned — 5 plans across 4 waves. W1: 06-01 (writer bug fix + RawDocument metadata field); W2: 06-02 (PDF loader + chunker) + 06-03 (YouTube loader + chunker) in parallel; W3: 06-04 (article loader + chunker); W4: 06-05 (pipeline orchestration + requirements.txt + human eval checkpoint). All 4 requirements covered: INGEST-08, INGEST-09, INGEST-10, EVAL-05.*
