# Phase 1: Schema, Forum Ingestion & Golden Eval Set - Context

**Gathered:** 2026-05-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Offline data pipeline only: forum `.txt` files in `raw_data/forum_posts/` → chunked, embedded, idempotently-stored rows in PostgreSQL/pgvector, plus a locked golden eval set authored post-ingestion and committed before any Phase 2 retrieval tuning begins.

**In scope:** DB schema creation, forum-post loader + chunker, Embedder Protocol (OpenAI implementation), content-hash dedup writer, HNSW index, golden eval set authoring tool and output.

**Out of scope:** PDF/article/YouTube ingestion (Phase 2), retrieval layer (Phase 2), FastAPI server (Phase 3), any UI (Phase 3+), gear aliases (Phase 2).

</domain>

<decisions>
## Implementation Decisions

### Forum Post Chunking
- **D-01:** Use **paragraph-packing** — treat each `.txt` file as one document, greedily accumulate paragraphs to a 300–500 token budget (measured via `tiktoken`), merge any paragraph block under 40 words forward into the next chunk rather than indexing it as a standalone micro-chunk.
- **D-02:** No quoted-reply stripping is needed — inspecting the actual files confirms no `>` or `[quote]` syntax is present. Files are flat blank-line-separated paragraphs.
- **D-03:** Include `source_filename` (e.g., `bb_king_tone.txt`) in chunk metadata so the eval authoring script can display provenance per chunk during human review. This field lives in `metadata_json` on the `chunks` table (or as a join through `documents.source_id`).
- **D-04:** Chunk IDs are stable `(source_id, chunk_index)` pairs — index resets to 0 per file. `--full-rebuild` flag truncates and re-chunks if chunking strategy changes.

### Schema Initialization
- **D-05:** **Standalone SQL script** — `scripts/init_db.sql` run once via `psql -f scripts/init_db.sql` before first pipeline invocation. Idempotent with `IF NOT EXISTS` guards. Keeps DDL explicit and inspectable outside the pipeline code.
- **D-06:** Script creates: `CREATE EXTENSION IF NOT EXISTS vector`, `CREATE EXTENSION IF NOT EXISTS pg_trgm` (for Phase 3 hybrid search headroom), `documents` table, `chunks` table with `vector(1536)` column, `ingest_runs` table, HNSW index on cosine distance with `m=16, ef_construction=64`.

### Eval Set Authoring (EVAL-01)
- **D-07:** **Scripted helper** — Plan 5 delivers `python -m app.eval.author`: presents top-K retrieval results per draft query (after ingestion Plans 1–4 complete), human accepts/rejects each candidate chunk, script writes `eval/golden_set.jsonl` with live chunk UUIDs directly from DB (no manual transcription).
- **D-08:** JSONL schema per tuple: `{"query": str, "expected_chunk_ids": [str], "expected_themes": [str], "held_out": bool}`.
- **D-09:** `expected_themes` uses a **fixed enum**: `["amp_settings", "pedal_choice", "signal_chain", "pickup_tone", "studio_vs_live"]` — stable labels needed for Phase 5 recall@K scoring comparability across runs.
- **D-10:** **Split:** 15 training / 5 held-out (one held-out query from 5 of the 10 forum topics). Held-out query indices committed to `eval/HELD_OUT.md` with an ISO timestamp immediately after authoring — before any Phase 2 retrieval parameter is touched.
- **D-11:** `eval/HELD_OUT.md` records: timestamp, list of held-out query indices, and a one-line statement that no retrieval tuning has been performed at time of commit.

### Python Packaging
- **D-12:** **`requirements.txt` only** — pinned versions per `research/STACK.md`. Optional `requirements-dev.txt` for pytest/ruff. No build tool, no editable install. `python -m app.ingest.pipeline` invoked from project root (where `app/` is a package).
- **D-13:** Python version pinned to **3.12** via `.python-version` file (for pyenv). `.env.example` committed with all required env var keys; `.env` gitignored.

### Claude's Discretion
- HNSW index parameters (`m=16, ef_construction=64`) — use research defaults; tune only if Phase 1 evaluation shows recall problems.
- Batch size for OpenAI embedding calls — use 64 per batch (safe across providers per research).
- `ingest_runs` status transitions (`running → completed | failed`) — implement straightforwardly.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Scope
- `.planning/REQUIREMENTS.md` §v1 Requirements — INGEST-01 through INGEST-06 and EVAL-01 define all Phase 1 acceptance criteria
- `.planning/ROADMAP.md` §Phase 1 — 5 plans, success criteria, and what's deferred

### Architecture & Schema
- `.planning/research/ARCHITECTURE.md` §Ingestion Pipeline — component boundaries (Loader → Normalizer → Chunker → Embedder → Writer), schema DDL for `documents`/`chunks`/`ingest_runs`, content-hash dedup algorithm, re-ingestion strategy
- `.planning/research/ARCHITECTURE.md` §Chunking Architecture — forum post chunking strategy, unified chunk metadata schema
- `.planning/research/STACK.md` §pgvector Schema — full DDL with HNSW index params, index choice rationale, retrieval query template

### Stack & Dependencies
- `.planning/research/STACK.md` §Recommended Stack Summary — all pinned versions
- `.planning/research/STACK.md` §Embedding Generation & Abstraction — full Embedder Protocol code (`base.py`, `openai_embedder.py`, `factory.py`), critical implementation notes (batch size, `embed_documents` vs `embed_query` split)
- `.planning/research/STACK.md` §FastAPI Project Layout — canonical `app/` directory structure
- `.planning/research/STACK.md` §Full requirements.txt — use this as the basis for Phase 1 `requirements.txt`

### Project Constraints
- `.planning/PROJECT.md` §Constraints — hard technology constraints (no LangChain/LlamaIndex, configurable embedding model, local PostgreSQL)
- `CLAUDE.md` §Architecture — one-way data flow, ingestion as offline CLI, Embedder Protocol rules

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — this is a greenfield phase. All `app/` code is created here.

### Established Patterns
- None established yet — Phase 1 sets the conventions that subsequent phases follow.

### Integration Points
- `raw_data/forum_posts/` — 10 `.txt` files, the only corpus input for Phase 1. Files are flat blank-line-separated paragraphs, ~500–1300 tokens total each, 20–71 lines each.
- PostgreSQL local instance — must be running with pgvector extension available before `scripts/init_db.sql` is run.
- `EMBEDDING_MODEL` env var — defaults to `text-embedding-3-small` (1536-d). The `vector(1536)` column is sized for this default.

</code_context>

<specifics>
## Specific Ideas

- Source filename (`bb_king_tone.txt`, etc.) must be present in chunk metadata visible to the eval authoring script — the user explicitly requested this so the human reviewer knows which forum topic each chunk comes from during EVAL-01 curation.
- The eval authoring script (`app/eval/author.py`) is the Phase 1 Plan 5 deliverable — it's not an ad-hoc helper but a committed, runnable module.
- `eval/HELD_OUT.md` must be committed with a timestamp *before* any Phase 2 retrieval tuning begins — this ordering is a hard constraint, not a suggestion.
- `pg_trgm` extension pre-installed in Phase 1 even though hybrid search is Phase 3 — deliberate headroom decision per ROADMAP.md Plan 1.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 1-Schema-Forum-Ingestion-Golden-Eval-Set*
*Context gathered: 2026-05-15*
