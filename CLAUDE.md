<!-- GSD:project-start source:PROJECT.md -->
## Project

**Guitar Tone Advisor** — Personal conversational web app where the user describes their gear + target tone and receives grounded, citation-backed recommendations (amp settings, pedal choices, signal chain order, knob positions) drawn from a curated corpus of forum posts, equipment manuals, web articles, and YouTube transcripts.

**Core value:** Given a user's gear and a target tone, produce concrete, cited settings recommendations they can immediately act on — no vague advice, no hallucinated gear.

**Audience:** Single user, fully local, no auth, no multi-tenancy.

See `.planning/PROJECT.md` for full context, requirements, and decisions.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->
## Technology Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend framework | FastAPI 0.136 + uvicorn | Async, ASGI |
| LLM SDK | `anthropic` 0.102 | Direct SDK — no LangChain, no LlamaIndex |
| Embeddings | `openai` 2.36 (text-embedding-3-small, 1536-d) | Configurable via `EMBEDDING_MODEL` env var |
| Database driver | `psycopg[binary]` 3.3.4 | psycopg **v3**, not v2 |
| Vector extension | `pgvector` 0.4.2 + PostgreSQL (local) | HNSW index, cosine distance |
| SSE streaming | `sse-starlette` 3.4.4 | Token-by-token chat streaming |
| PDF parsing | `pypdf` 6.11 primary; `pymupdf4llm` escalation | pymupdf4llm for table-heavy manuals |
| Article scraping | `trafilatura` 2.0 | Not newspaper3k (abandoned) |
| YouTube transcripts | `youtube-transcript-api` 1.2.4 | Pin version; `yt-dlp` as fallback |
| Frontend | Next.js | Proxies `/api/py/*` → `localhost:8000` via rewrites |
| Settings | `pydantic-settings` + `python-dotenv` | All config via env vars |

**Explicit non-deps:** LangChain, LlamaIndex, langchain-text-splitters, chromadb, qdrant, newspaper3k, psycopg2.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.

Key constraints to respect:
- Retrieval code must never import `openai` or `voyageai` directly — go through the `Embedder` Protocol
- `embed_documents()` and `embed_query()` are always called separately — don't conflate them
- Chunking dispatches on `source_type` — no universal chunker
- Never split inside a table during PDF chunking
- All external API calls wrapped with `tenacity` retry/backoff
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

**One-way data flow:** `raw_data/` → ingestion CLI → Postgres/pgvector → FastAPI → SSE → Next.js

**Ingestion** is an offline CLI (`python -m app.ingest.pipeline`) — not an API endpoint. It writes to Postgres; the API only reads. Re-runs are safe via content-hash dedup. `--full-rebuild` truncates and re-embeds.

**Retrieval** uses HNSW cosine distance (`<=>`, `vector_cosine_ops`). Dense-only for Phase 1–2; hybrid `tsvector + RRF` added in Phase 5. Gear aliases expanded bidirectionally before query embedding.

**Generation:** Sources injected as `<sources>` XML block with stable `S1..Sn` IDs. Citations are `[S{n}]` inline. Citations sent as an out-of-band SSE `event: citations` payload after the token stream. Temperature 0.0–0.2.

**Session memory:** In-process Python dict keyed by `session_id`. Gear context lives in the first user turn as a `<gear>` block (system prompt stays stable for prompt caching). Server restart clears sessions — acceptable for single-user local tool.

**pgvector schema:** `documents` (source registry) + `chunks` (text + vector + metadata) + `ingest_runs` (audit log). `embedding_model` column on `chunks` — never mix vectors from different models in the same table.

**Next.js:** Dev rewrites proxy `/api/py/*` → `localhost:8000`. No CORS config.

See `.planning/research/ARCHITECTURE.md` for full component boundaries and build order.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to `.claude/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` — do not edit manually.
<!-- GSD:profile-end -->
