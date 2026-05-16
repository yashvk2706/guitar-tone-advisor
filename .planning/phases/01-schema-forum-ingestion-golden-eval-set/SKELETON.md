# Walking Skeleton — Guitar Tone Advisor

**Phase:** 1
**Generated:** 2026-05-15

## Capability Proven End-to-End

A user can run `python -m app.ingest.pipeline` from the project root, watch every `.txt` file in `raw_data/forum_posts/` get chunked, embedded with OpenAI `text-embedding-3-small`, and inserted (or skipped via content-hash dedup) into a local Postgres `chunks` table behind an HNSW cosine index — then run `python -m app.eval.author` to produce `eval/golden_set.jsonl` (≥20 tuples) with the held-out split locked in `eval/HELD_OUT.md` before any retrieval tuning begins.

> Phase 1 is the offline data-pipeline backbone of the Walking Skeleton. There is no HTTP surface or browser UI yet — that is Phase 3's slice. Phase 1 proves: filesystem corpus → chunker → embedder → Postgres/pgvector → audited ingest_runs → eval set on disk. Phases 2/3 add retrieval and the FastAPI+Next.js slice on top of this backbone without revisiting these architectural decisions.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Language / runtime | Python 3.12 (pinned via `.python-version`) | D-13 — broad wheel coverage, stable; CLAUDE.md hard constraint. |
| Web framework (later phases) | FastAPI 0.136.1 + uvicorn[standard] 0.46.0 | STACK.md — async ASGI, integrates cleanly with psycopg3 pool. Not exercised in Phase 1. |
| Database | Local PostgreSQL with `vector` and `pg_trgm` extensions | STACK.md — pgvector is the only retrieval store; `pg_trgm` pre-installed in Phase 1 for Phase 3 hybrid-search headroom (D-06). |
| Database driver | `psycopg[binary]==3.3.4` (psycopg v3, NOT v2) | STACK.md — first-class pgvector adapter, sync+async on one conn, modern API. CLAUDE.md hard constraint. |
| Vector extension client | `pgvector==0.4.2` | STACK.md pinned version; provides `register_vector(conn)`. |
| Embeddings | `openai==2.36.0`, `text-embedding-3-small` (1536-d) by default | INGEST-03; STACK.md. Configurable via `EMBEDDING_MODEL` env var. Embedder Protocol isolates the call. |
| Embedder abstraction | `Embedder` Protocol in `app/embeddings/base.py` with `embed_documents` / `embed_query` split + `factory.get_embedder()` dispatch on env var | STACK.md §Embedding Generation — retrieval code never imports `openai` directly; protocol preserved for Voyage/local fallbacks in later phases. CLAUDE.md hard constraint. |
| Chunking strategy | Paragraph-packing, 300–500 token budget, no quoted-reply stripping (D-01, D-02). Dispatch on `source_type` even though only `forum` exists in Phase 1. | D-01/D-02; ARCHITECTURE.md §Chunking; CLAUDE.md hard constraint ("Chunking dispatches on source_type"). |
| Token counting | `tiktoken==0.12.0`, `cl100k_base` encoder | STACK.md §Chunking Strategy. Matches OpenAI embedding family. |
| Retry / backoff for external calls | `tenacity==9.1.4` (`stop_after_attempt(5)`, `wait_exponential(min=1, max=30)`) | STACK.md §Embedding implementation; CLAUDE.md hard constraint. |
| Schema initialization | Standalone `scripts/init_db.sql`, idempotent (`IF NOT EXISTS`), run once via `psql -f scripts/init_db.sql` | D-05 — keeps DDL explicit and inspectable outside pipeline code. |
| Schema tables | `documents`, `chunks` (with `vector(1536)` column), `ingest_runs` | INGEST-04; ARCHITECTURE.md §Ingestion Pipeline; D-06. |
| Index strategy | HNSW with `vector_cosine_ops`, `m=16, ef_construction=64`; `<=>` cosine operator at query time | INGEST-05; STACK.md §pgvector Schema; D-06. HNSW works on empty table (IVFFlat does not). |
| Idempotency | Content-hash dedup keyed on `(source_id, chunk_index, embedding_model)` UNIQUE constraint + `sha256(normalized_text)` per chunk; `--full-rebuild` flag truncates `chunks` for strategy changes | INGEST-06; ARCHITECTURE.md §Re-ingestion; D-04. |
| Packaging | `requirements.txt` (pinned per STACK.md) + optional `requirements-dev.txt`. No build tool, no editable install. Invoked as `python -m app.ingest.pipeline` from project root. | D-12. |
| Config / secrets | `pydantic-settings` 2.14.1 + `python-dotenv` 1.2.2. `.env.example` committed, `.env` gitignored. Required keys: `DATABASE_URL`, `OPENAI_API_KEY`, `EMBEDDING_MODEL`. | D-13; STACK.md. Secrets never hardcoded; never f-string'd into SQL. |
| Directory layout | `app/{ingest,embeddings,eval}/` + `scripts/init_db.sql` + `tests/` + `eval/` + `raw_data/` (gitignored) per STACK.md §FastAPI Project Layout. `ingest` and `eval` are CLI-only Python packages, not imported by any HTTP layer. | STACK.md canonical layout; D-12. |
| CLI entry points | `python -m app.ingest.pipeline [--full-rebuild]` for ingestion; `python -m app.eval.author` for golden-set authoring | INGEST-01; D-07; D-12. |
| Eval set format | `eval/golden_set.jsonl` — one JSON object per line with schema `{query, expected_chunk_ids, expected_themes, held_out}`; themes drawn from fixed enum `[amp_settings, pedal_choice, signal_chain, pickup_tone, studio_vs_live]` | EVAL-01; D-08; D-09. |
| Held-out manifest | `eval/HELD_OUT.md` records ISO timestamp + held-out query indices + statement that no retrieval tuning has been performed at time of commit | EVAL-01; D-10; D-11. |

## Stack Touched in Phase 1

- [x] **Project scaffold** — `requirements.txt`, `requirements-dev.txt`, `.python-version` (3.12), `.env.example`, `.gitignore` additions, `app/__init__.py`, package directories.
- [x] **CLI entry points** — `python -m app.ingest.pipeline` (real ingestion) and `python -m app.eval.author` (eval authoring). No HTTP surface in Phase 1.
- [x] **Database — real reads AND real writes** — `scripts/init_db.sql` creates schema; pipeline inserts into `documents`, `chunks`, `ingest_runs`; eval authoring reads `chunks` to surface candidates; idempotent re-run reads `(source_id, chunk_index, embedding_model)` to skip.
- [x] **UI** — N/A in Phase 1. The "interactive element" of the skeleton is the CLI; Phase 3 adds the Next.js chat. This is explicit and intentional — the user story focuses on the data backbone first.
- [x] **Deployment** — Fully local. Documented local-run command: `psql -f scripts/init_db.sql && python -m app.ingest.pipeline && python -m app.eval.author`. No hosting, no CORS, no auth.

## Out of Scope (Deferred to Later Slices)

- **PDF manuals, web articles, YouTube transcripts** — Phase 2 (INGEST-08/09/10). Forum-only chunker dispatch in Phase 1.
- **Quoted-reply stripping** — D-02: not needed for the current corpus.
- **Retrieval layer** (`retrieve()` function, `register_vector(conn)` on a pool, gear-alias expansion) — Phase 2.
- **`gear_aliases.json`** — Phase 2 (INGEST-07).
- **FastAPI server, SSE streaming, `/chat`, `/sources/{chunk_id}`, `/health`, `/ingest/status`** — Phase 3.
- **Next.js chat UI, citations drawer, "New chat" button** — Phase 3 / Phase 4.
- **Voyage AI embedder, sentence-transformers local fallback** — Embedder Protocol shape is locked in Phase 1, but only `OpenAIEmbedder` is implemented. Factory dispatch supports `voyage-*` and `local:*` prefixes via `NotImplementedError` for now.
- **Hybrid (BM25) retrieval, RRF fusion, `tsvector` index** — Phase 3+. `pg_trgm` extension is pre-installed in Phase 1 as deliberate headroom (D-06; ROADMAP.md Plan 1).
- **Reranking, multi-query rewriting, per-source-type weighting** — Phase 3+.
- **`/sessions/{id}` endpoint, in-process session memory, sliding-window truncation, `<gear>` block placement** — Phase 3.
- **Eval scoring harness (recall@K, MRR, RAGAS faithfulness, empty-context refusal smoke test)** — Phase 5. Phase 1 only authors `eval/golden_set.jsonl`; Phase 5 consumes it without modification.

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering the Phase 1 schema, Embedder Protocol shape, chunk metadata fields, or eval-set JSONL schema:

- **Phase 2:** Retrieval Layer & Gear Aliases — `app/retrieval/retriever.py` (HNSW cosine search, K=8), `app/retrieval/aliases.py` (bidirectional gear-alias expansion), `gear_aliases.json`. Reads `chunks` via Embedder Protocol's `embed_query`. No schema changes.
- **Phase 3:** Grounded Generation & Minimal Chat UI — FastAPI app (`app/main.py`), `POST /chat` with SSE token stream + out-of-band `event: citations`, `GET /sources/{chunk_id}`, in-process session dict, `<gear>` block convention, minimal Next.js chat UI with `/api/py/*` rewrites. Reads via Phase 2 retriever; no schema changes.
- **Phase 4:** UI Polish — Knobs, Markdown, Follow-ups — purely frontend. No backend changes.
- **Phase 5:** Evaluation Harness & Grounding Quality — `app/eval/retrieval.py` (recall@K + MRR), `app/eval/refusal.py` (empty-context smoke test), `app/eval/ragas.py`. Loads `eval/golden_set.jsonl` written in Phase 1; never re-authors it.

---

*Walking Skeleton recorded 2026-05-15. Architectural decisions above are contracts for subsequent phases — Phases 2–5 may add components but must not change the schema, the Embedder Protocol's two-method signature, the `(source_id, chunk_index, embedding_model)` chunk identity, or the eval JSONL schema.*
