# Phase 7: Persistent Corpus & Cloud Deployment - Context

**Gathered:** 2026-06-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Two coupled deliverables:
1. **Persistence documentation** — Verify that `docker-compose down` (without `-v`) retains the corpus across restarts (the `pgdata` named volume already exists), and document in `RUNNING.md` that `docker-compose down -v` destroys all corpus data and must never be used in normal operation.
2. **Cloud deployment** — Containerize the FastAPI backend (Dockerfile) and deploy to Railway; deploy Next.js frontend to Vercel; provision Railway Postgres with pgvector addon; restore a pre-seeded corpus via pg_dump/restore; expose the app at public HTTPS URLs.

**In scope:** `Dockerfile` for FastAPI; Railway service configuration; `RUNNING.md` persistence warning; `scripts/start.sh` startup script (schema init + uvicorn); `next.config.js` env-var rewrite; Vercel deployment; pg_dump/restore of the full corpus; YouTube transcript fix (yt-dlp `--cookies-from-browser chrome`); `ANTHROPIC_API_KEY` + `OPENAI_API_KEY` as Railway env vars; README deployment instructions.

**Out of scope:** Multi-region deployment, CDN caching, CI/CD pipeline, Alembic migrations, separate ingest Docker image, monitoring/alerting, auth.

</domain>

<decisions>
## Implementation Decisions

### Deployment Platform
- **D-01:** Use **Railway** instead of AWS EC2. FastAPI backend as a Railway service; Postgres with pgvector as a Railway managed database addon (Railway's Postgres addon supports `CREATE EXTENSION vector`). ROADMAP references AWS EC2 — this discussion overrides that to Railway.
- **D-02:** Next.js frontend deployed to **Vercel** (free tier, native Next.js support). Separate from Railway infra; HTTPS handled automatically.
- **D-03:** HTTPS for both services is handled automatically by Railway (backend subdomain) and Vercel (frontend subdomain). No nginx, Caddy, or ALB needed.

### API Routing & CORS
- **D-04:** Keep the existing `/api/py/*` Next.js rewrite pattern. On Vercel, rewrites proxy server-side (Vercel → Railway) — no browser CORS exposure, Railway URL not visible to the browser.
- **D-05:** Update `next.config.js` rewrite destination from `http://localhost:8000` to `process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'`. Set `NEXT_PUBLIC_API_URL` to the Railway FastAPI service URL in Vercel's environment settings. Local dev behavior unchanged.
- **D-06:** No CORS middleware needed in FastAPI for the Vercel→Railway rewrite path (server-side proxy, not browser cross-origin). Only add CORS if direct browser access to Railway is ever needed.

### Dockerfile (FastAPI)
- **D-07:** Single-stage `Dockerfile` using `python:3.12-slim`. Pattern: `COPY requirements.txt` → `pip install --no-cache-dir -r requirements.txt` → `COPY app/ scripts/` → `CMD`.
- **D-08:** Ingest pipeline CLI (`python -m app.ingest.pipeline`) is included in the production image. Same image serves both the API and ad-hoc pipeline re-runs.
- **D-09:** Container startup runs a `scripts/start.sh` wrapper that: (1) runs `psql $DATABASE_URL -f scripts/init_db.sql` (idempotent — uses `CREATE EXTENSION IF NOT EXISTS vector` and `CREATE TABLE IF NOT EXISTS`), then (2) starts `uvicorn app.main:app --host 0.0.0.0 --port 8000`. This ensures schema is always present after deploy without manual steps.

### Railway Postgres Setup
- **D-10:** Schema initialization (pgvector extension + tables + HNSW index) runs automatically on every container start via `scripts/start.sh` (D-09). The `init_db.sql` script must use `IF NOT EXISTS` guards throughout to be safe on re-deploys.
- **D-11:** `DATABASE_URL`, `OPENAI_API_KEY`, and `ANTHROPIC_API_KEY` are set as Railway environment variables via the Railway dashboard. Never committed to the repo.

### Corpus Pre-Seeding
- **D-12:** Fix YouTube transcript extraction locally **before** deploying. Add `--cookies-from-browser chrome` (or a cookies.txt path) to the `yt-dlp` fallback command in `app/ingest/loader.py`. Run the full pipeline locally (all 4 source types including all 13 YouTube videos) to get a complete corpus in the local Docker Postgres.
- **D-13:** Transfer corpus to Railway via **pg_dump/restore**: `pg_dump` the local Docker Postgres after the full pipeline run → copy the dump → `psql $RAILWAY_DATABASE_URL < dump.sql` (or `pg_restore`). No API keys needed on Railway during this step.

### Docker Volume Persistence
- **D-14:** The existing `docker-compose.yml` `pgdata` named volume already provides persistence. `docker-compose down` (without `-v`) is safe. `docker-compose down -v` deletes the volume and destroys the corpus — document this prominently in `RUNNING.md`.
- **D-15:** Create `RUNNING.md` at project root with a warning block: "⚠️ Never run `docker-compose down -v` — this deletes `pgdata` and destroys all ingested corpus data. You would need to re-run the full ingestion pipeline."

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Infrastructure
- `docker-compose.yml` — Current local orchestration; `pgdata` named volume already defined; production adds only `docker-compose.prod.yml` or Railway config
- `scripts/init_db.sql` — Schema DDL (pgvector extension, documents/chunks/ingest_runs tables, HNSW index); must be made fully idempotent (`IF NOT EXISTS`) for D-09/D-10
- `app/config.py` — `Settings` class; `database_url`, `openai_api_key`, `anthropic_api_key`, `embedding_model` fields; all sourced from env vars
- `app/main.py` — FastAPI entry point; `uvicorn app.main:app` is the production CMD
- `app/ingest/loader.py` — YouTube loader with yt-dlp fallback; fix `--cookies-from-browser chrome` here for D-12

### Frontend
- `frontend/next.config.js` — Current rewrite hardcodes `http://localhost:8000`; D-05 changes this to env var
- `frontend/package.json` — Node/Next.js version; needed for Vercel build config

### Phase 6 Corpus Artifacts
- `eval/golden_set.jsonl` + `eval/HELD_OUT.md` — Eval set; recall@8 ≥ 1.0 and MRR ≥ 0.9 already achieved on Phase 6 corpus
- `app/eval/retrieval.py` — Run after corpus restore on Railway to sanity-check the restore succeeded

### Project Constraints
- `CLAUDE.md` — Tech stack constraints; `ANTHROPIC_API_KEY` never committed; Embedder Protocol (no direct `openai` import outside embedder)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/init_db.sql` — Schema already written; needs `IF NOT EXISTS` guards added to every DDL statement for idempotent startup
- `app/ingest/loader.py::load_youtube_transcripts()` — yt-dlp fallback already wired; only the command string needs `--cookies-from-browser chrome` added
- `frontend/next.config.js` — Minimal change: `'http://localhost:8000'` → `process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'`

### Established Patterns
- Per-request `get_conn()` pattern in `app/main.py` — compatible with Railway's Postgres connection string format; no connection pooling changes needed
- `app/config.py::get_settings()` — Railway sets env vars as process env; `pydantic-settings` picks them up automatically; no code changes needed for env var sourcing

### Integration Points
- Railway DATABASE_URL format: `postgresql://user:pass@host:port/db` — same format as local; `app/config.py` `database_url` field consumes it directly
- Vercel's `NEXT_PUBLIC_API_URL` → `next.config.js` rewrite destination → Railway FastAPI service public URL (e.g., `https://guitar-tone-advisor.up.railway.app`)

</code_context>

<specifics>
## Specific Ideas

- Single Docker image handles both API serving and ingest pipeline (no second Dockerfile)
- `scripts/start.sh` wrapper pattern for schema-init-before-start (avoids a separate migration service)
- Railway free plan covers the use case (personal tool, low traffic)

</specifics>

<deferred>
## Deferred Ideas

- CI/CD pipeline (auto-deploy on push to main) — future improvement, not needed for v1
- Monitoring / uptime alerting — out of scope for personal tool
- Alembic for schema migrations — overkill for a stable schema; re-evaluate if schema evolves significantly
- Multi-region or CDN caching — not needed for single-user personal tool

</deferred>

---

*Phase: 7-persistent-corpus-cloud-deployment*
*Context gathered: 2026-06-02*
