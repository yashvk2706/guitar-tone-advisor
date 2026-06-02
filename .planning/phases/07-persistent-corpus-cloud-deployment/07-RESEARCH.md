# Phase 7: Persistent Corpus & Cloud Deployment - Research

**Researched:** 2026-06-02
**Domain:** Docker, Railway, Vercel, pg_dump/restore, yt-dlp EJS, FastAPI deployment
**Confidence:** HIGH (most claims verified via tool calls and live tests)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Railway for FastAPI backend + managed pgvector Postgres (pgvector/pgvector:pg17 template). Not AWS EC2.
- **D-02:** Vercel for Next.js frontend.
- **D-03:** HTTPS automatic on Railway subdomain + Vercel subdomain. No nginx/Caddy.
- **D-04:** Keep `/api/py/*` rewrite pattern. Vercel proxies server-side to Railway.
- **D-05:** Update `next.config.js` rewrite destination to `process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'`.
- **D-06:** No CORS middleware needed.
- **D-07:** Single-stage `Dockerfile` using `python:3.12-slim`.
- **D-08:** Same image for both API serving and ingest pipeline CLI.
- **D-09:** `scripts/start.sh` runs `psql $DATABASE_URL -f scripts/init_db.sql` then `uvicorn`.
- **D-10:** `init_db.sql` must use `IF NOT EXISTS` throughout (already done — verified).
- **D-11:** `DATABASE_URL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` as Railway env vars, never committed.
- **D-12:** Fix yt-dlp YouTube transcript extraction locally before deploying. Add `--cookies-from-browser chrome` to `_load_via_ytdlp()` in `app/ingest/loader.py`.
- **D-13:** Transfer corpus via `pg_dump` (local Docker Postgres) → `psql $RAILWAY_DATABASE_PUBLIC_URL`.
- **D-14:** Document `docker-compose down -v` danger in `RUNNING.md`.
- **D-15:** Create `RUNNING.md` at project root with prominent warning block.

### Claude's Discretion

None specified beyond the above locked decisions.

### Deferred Ideas (OUT OF SCOPE)

- CI/CD pipeline (auto-deploy on push to main)
- Monitoring / uptime alerting
- Alembic for schema migrations
- Multi-region or CDN caching
- docker-compose.prod.yml (Railway handles the production orchestration)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PERSIST-01 | `docker-compose down` (without `-v`) retains all corpus chunks; documented in `RUNNING.md` | Confirmed: `pgdata` named volume in `docker-compose.yml` already provides persistence across `down`/`up` cycles. The `-v` flag destroys volumes and is the ONLY danger. |
| DEPLOY-01 | `Dockerfile` exists for FastAPI backend | Research covers exact structure for `python:3.12-slim` with `psycopg[binary]` (no apt-get needed), start script wiring. |
| DEPLOY-02 | App reachable at public HTTPS URL | Railway auto-provisions HTTPS subdomain `.up.railway.app`. Vercel auto-provisions HTTPS. No extra config needed. |
| DEPLOY-03 | API keys stored as Railway env vars, never committed | `.env` is already gitignored. Railway dashboard env vars confirmed as the correct pattern. |
| DEPLOY-04 | Deployed Postgres has full corpus pre-seeded via pg_dump/restore | Exact commands documented. pg_dump uses Docker exec; psql restore uses Railway `DATABASE_PUBLIC_URL`. |
| DEPLOY-05 | Next.js frontend deployed to Vercel; rewrite proxies to Railway | Vercel Root Directory setting + `NEXT_PUBLIC_API_URL` env var covers this. |
</phase_requirements>

---

## Summary

Phase 7 has two parallel workstreams: (1) a documentation task that confirms the existing `pgdata` Docker volume already provides corpus persistence and writes a `RUNNING.md` warning about `docker-compose down -v`; (2) a cloud deployment track that produces a `Dockerfile`, `scripts/start.sh`, railway service configuration, updated `next.config.js`, Vercel deployment, and a pg_dump/restore to pre-seed Railway Postgres with the local corpus.

The most complex piece is the YouTube transcript fix. Live testing in this session confirmed that the yt-dlp fallback in `_load_via_ytdlp()` fails due to two compounding issues: (a) the `--js-runtimes nodejs` flag uses the wrong runtime name (`node` is correct), and (b) the EJS n-challenge solver (`yt-dlp-ejs` package) is not installed in `requirements.txt`. Both must be fixed before running the full pipeline that produces the pg_dump. The `--cookies-from-browser chrome` flag works on this macOS system (3,289 cookies extracted successfully), and `youtube-transcript-api` primary path is blocked by IP (RequestBlocked), making the yt-dlp fallback the only viable path.

The `init_db.sql` is already fully idempotent (all DDL uses `IF NOT EXISTS` — verified). The `scripts/start.sh` pattern (psql init + uvicorn) is the accepted Railway startup approach. `psycopg[binary]` installs via manylinux wheel with no apt-get build dependencies on `python:3.12-slim`.

**Primary recommendation:** Fix yt-dlp first (two-line change: remove `--js-runtimes nodejs`, add `--cookies-from-browser chrome`; add `yt-dlp[default]` to `requirements.txt`), run full pipeline to get 656+ chunks including YouTube, then proceed with Dockerfile and Railway/Vercel deploy.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| API serving (POST /chat, GET /sources, GET /health) | Railway (FastAPI container) | — | Backend logic; must reach Postgres |
| Postgres + pgvector corpus | Railway (pgvector/pgvector:pg17 container) | — | DB tier; co-located with backend in Railway project |
| Static schema init | Railway (start.sh on container start) | — | Runs idempotent DDL before uvicorn |
| Next.js UI | Vercel (serverless SSR) | — | Native Next.js hosting; auto-HTTPS |
| API proxy (`/api/py/*` → Railway) | Vercel (server-side rewrite) | — | Keeps Railway URL hidden from browser; no CORS needed |
| HTTPS termination | Railway + Vercel (automatic) | — | Both platforms provision TLS certificates automatically |
| Corpus seeding | Local Docker → pg_dump → Railway psql | — | One-time operator action; not automated |
| Secret management | Railway env vars | `.env` (local only, gitignored) | Never in repo; Railway dashboard injection |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| python:3.12-slim | official Docker image | Base image for FastAPI container | Minimal size; manylinux wheels install without build tools |
| psycopg[binary] | 3.3.4 (pinned in requirements.txt) | Postgres driver | Binary wheel — no apt-get gcc/libpq-dev needed on slim |
| pgvector (Python) | 0.4.2 | Vector type registration for psycopg | Required for `register_vector()` |
| uvicorn[standard] | 0.46.0 | ASGI server | Already pinned; Railway uses `$PORT` env var |
| yt-dlp[default] | 2026.3.17 | YouTube transcript extraction with EJS n-challenge solver | `[default]` extras install `yt-dlp-ejs` package which is required for n-challenge solving |
| yt-dlp-ejs | 0.8.0 (installed by `yt-dlp[default]`) | EJS challenge solver scripts for YouTube | Without this package, yt-dlp shows "JS runtimes: none" even with Node present |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pgvector/pgvector:pg17 | Railway template | Railway Postgres with vector extension | Deploy via Railway template marketplace, not the standard Postgres addon |
| pg_dump (PostgreSQL 17) | via Docker exec on local container | Corpus backup before transfer | Run against local Docker container to produce dump.sql |
| psql client | install via `brew install libpq` | Restore corpus to Railway | Needed locally for `psql $RAILWAY_DATABASE_PUBLIC_URL < dump.sql` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `python:3.12-slim` | `python:3.12-alpine` | Alpine uses musl libc; manylinux wheels (psycopg[binary]) don't run on musl — requires recompile. Use slim/debian only. |
| pg_dump plain text | pg_dump custom format (`-F c`) | Custom format is smaller and pg_restore can parallelize; plain text (`-F p`) works with `psql` directly and is simpler to troubleshoot. For this corpus (656 chunks), plain text is fine. |
| `scripts/start.sh` wrapper | Dockerfile `ENTRYPOINT` | Both work; start.sh is more transparent and easier to test locally. |
| `--cookies-from-browser chrome` | `--cookies cookies.txt` (Netscape format) | cookies.txt is more portable (no local Chrome dependency); but requires manual export step. Chrome cookies work on this macOS machine. |

**Version verification:** Confirmed via `pip index versions` and `npm view next version`:
- psycopg-binary: 3.3.4 (current as of 2026-06-02) [VERIFIED: pip index]
- yt-dlp: 2026.3.17 (current in venv) [VERIFIED: venv/bin/yt-dlp --version]
- Next.js: 16.2.7 (registry latest; project uses 16.2.6) [VERIFIED: npm view next]

---

## Architecture Patterns

### System Architecture Diagram

```
User Browser
    │
    │ HTTPS  
    ▼
Vercel (Next.js 16.2.6)
├── GET /                    → serves React UI
└── /api/py/:path*           → server-side rewrite (NEXT_PUBLIC_API_URL)
         │
         │ HTTPS (server-side, not browser)
         ▼
Railway FastAPI Service (python:3.12-slim container)
├── GET  /health             → {"status": "ok"}
├── POST /chat               → SSE stream
└── GET  /sources/{chunk_id} → chunk text
         │
         │ postgresql:// (private Railway network)
         ▼
Railway pgvector/pgvector:pg17 Container
└── guitar_tone_advisor DB
    ├── documents (35 rows: 10 forum + 15 pdf + 10 article)
    ├── chunks (656+ rows: 21 forum + 625 pdf + 10 article + N youtube)
    └── ingest_runs (audit log)
```

**Container startup flow (D-09):**
```
scripts/start.sh
    ├── psql $DATABASE_URL -f scripts/init_db.sql   # idempotent DDL
    └── uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

### Recommended Project Structure

```
guitar-tone-advisor/
├── Dockerfile                  # NEW: python:3.12-slim single-stage
├── scripts/
│   ├── init_db.sql             # EXISTING (already fully idempotent)
│   └── start.sh                # NEW: schema init + uvicorn
├── RUNNING.md                  # NEW: persistence warning + local setup docs
├── app/                        # EXISTING: no changes needed
├── frontend/
│   └── next.config.js          # MODIFY: localhost:8000 → env var
└── requirements.txt            # MODIFY: add yt-dlp[default] extras
```

### Pattern 1: Dockerfile for python:3.12-slim with psycopg[binary]

**What:** Single-stage Dockerfile for FastAPI + ingest pipeline. `psycopg[binary]` uses manylinux wheels — no apt-get build tools needed.

**When to use:** Any Python 3.12 + psycopg[binary] container.

```dockerfile
# Source: verified via psycopg-binary PyPI page + live test knowledge
FROM python:3.12-slim

WORKDIR /app

# Copy requirements first for layer cache efficiency
COPY requirements.txt ./
# psycopg[binary] installs via manylinux wheel — no gcc/libpq-dev needed
# yt-dlp-ejs (bundled in yt-dlp[default]) needs no system deps either
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY data/ ./data/

# scripts/start.sh must be executable
RUN chmod +x scripts/start.sh

# Railway injects PORT at runtime; fallback to 8000 for local docker run
# Use SHELL form (not exec form) so ${PORT} expands at runtime
CMD ["scripts/start.sh"]
```

**Critical note:** Do NOT use exec form `CMD ["uvicorn", "...", "$PORT"]` — shell variables don't expand in exec form. Either use a start.sh script (recommended per D-09) or use shell form `CMD uvicorn ... --port ${PORT:-8000}`.

### Pattern 2: scripts/start.sh (D-09)

```bash
#!/usr/bin/env bash
# Source: Railway pattern verified via docs.railway.com/guides/rag-pipeline-pgvector
set -e

echo "Running schema initialization..."
psql "$DATABASE_URL" -f scripts/init_db.sql

echo "Starting uvicorn on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
```

**Notes:**
- `set -e` ensures a failed psql init aborts the container startup (Railway marks deployment failed).
- `exec` replaces the bash process so uvicorn receives signals correctly (SIGTERM for graceful shutdown).
- `${PORT:-8000}` provides local dev fallback while accepting Railway's injected `PORT` (always 8080 on Railway at runtime).

### Pattern 3: Railway PORT Variable

**What:** Railway injects `PORT=8080` at container runtime. Application must listen on this port.

**Key gotcha — exec form vs shell form:**
```dockerfile
# WRONG: exec form does not expand shell variables
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$PORT"]

# CORRECT option A: shell form (expands variables)
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

# CORRECT option B: shell script (cleanest, aligns with D-09)
CMD ["scripts/start.sh"]
```

### Pattern 4: pg_dump Local Docker → Railway Restore

**What:** Transfer the 656-chunk corpus from local Docker Postgres to Railway.

```bash
# Step 1: Dump from local Docker container (pg_dump is inside the container)
# Source: verified via docker exec approach (pg_dump 17.10 confirmed in container)
docker exec guitar-tone-advisor-db-1 \
  pg_dump -U postgres -d guitar_tone_advisor -F p \
  > corpus_dump.sql

# Step 2: Install psql client locally if not present
brew install libpq
export PATH="/opt/homebrew/opt/libpq/bin:$PATH"  # or /usr/local/opt/libpq/bin on Intel

# Step 3: Restore to Railway (use DATABASE_PUBLIC_URL from Railway Variables tab)
# DATABASE_PUBLIC_URL format: postgresql://postgres:PASSWORD@HOST:PORT/railway
psql "$RAILWAY_DATABASE_PUBLIC_URL" < corpus_dump.sql
```

**Notes:**
- Use plain text format (`-F p`) for simplicity — allows direct `psql` restore without `pg_restore`.
- The Railway pgvector template provides `DATABASE_PUBLIC_URL` for external connections and `DATABASE_URL` for inter-service connections (internal Railway network).
- Railway's pgvector/pgvector:pg17 container uses the same Postgres wire protocol — the restore is a standard psql operation.
- `CREATE EXTENSION IF NOT EXISTS vector` runs automatically via `init_db.sql` on first container startup, so the extension is present before the restore.

### Pattern 5: Vercel Next.js Subfolder Deployment

**What:** Deploy `frontend/` subdirectory (not repo root) to Vercel.

**Configuration:**
1. In Vercel Dashboard → Project Settings → General → **Root Directory**: set to `frontend`
2. Build Command: `next build` (auto-detected for Next.js)
3. Output Directory: `.next` (auto-detected)
4. Environment Variables → Add `NEXT_PUBLIC_API_URL` = `https://<your-railway-service>.up.railway.app`

**next.config.js change (D-05):**
```javascript
// Source: direct code reading of frontend/next.config.js
/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/py/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/:path*`,
      },
    ];
  },
};
module.exports = nextConfig;
```

**Critical:** `NEXT_PUBLIC_API_URL` is embedded at **build time** (not runtime) because it is a `NEXT_PUBLIC_` variable. If you change Railway's URL after deploying Vercel, you must trigger a Vercel redeploy.

### Pattern 6: yt-dlp Fix for YouTube Transcript Extraction

**What:** Fix `_load_via_ytdlp()` in `app/ingest/loader.py` to (a) use correct cookie flag, (b) fix runtime flag, and (c) install EJS package.

**Root cause (verified via live testing this session):**
1. `--cookies-from-browser chrome` works: extracts 3,287+ cookies from Chrome on this macOS system.
2. `--js-runtimes nodejs` is wrong — the correct flag value is `node` (or omit it, yt-dlp auto-detects).
3. The EJS n-challenge solver (`yt-dlp-ejs` package) was not installed. Even with node in PATH, yt-dlp shows `[debug] JS runtimes: none` and `node (unavailable)` until `yt-dlp[default]` or `yt-dlp-ejs` is installed.
4. After installing `yt-dlp-ejs==0.8.0` via `pip install "yt-dlp[default]"`, the EJS distribution is available but the n-challenge still fails because `yt-dlp-ejs` requires a working Node.js >= 20. The `--js-runtimes nodejs` flag maps to `node` internally but was wrong in the original code.

**Three-part fix required:**

Part A — `requirements.txt`: change `yt-dlp` → `yt-dlp[default]` (installs yt-dlp-ejs):
```
yt-dlp[default]
```

Part B — `app/ingest/loader.py` in `_load_via_ytdlp()`, change the `cmd` list:
```python
cmd = [
    "yt-dlp",
    "--cookies-from-browser", "chrome",  # ADD: authenticate to bypass IP block
    "--write-auto-subs",
    "--sub-lang", "en",
    "--sub-format", "vtt",
    "--skip-download",
    # REMOVE: "--js-runtimes", "nodejs",  ← wrong flag value; EJS auto-detects runtime
    f"https://www.youtube.com/watch?v={video_id}",
    "-o", out_tmpl,
]
```

Part C — verify Node.js >= 20 is in PATH when the pipeline runs. Node 22.17.0 is available at `~/.nvm/versions/node/v22.17.0/bin/node`. Activate it before running the pipeline:
```bash
export PATH="$HOME/.nvm/versions/node/v22.17.0/bin:$PATH"
python -m app.ingest.pipeline --youtube-ids raw_data/youtube_ids.txt
```

**Alternative if Chrome cookies still fail:** Export a Netscape-format cookies.txt from Chrome using the "Get cookies.txt LOCALLY" browser extension, then use:
```python
"--cookies", "cookies.txt",  # instead of --cookies-from-browser chrome
```

**youtube-transcript-api cookie fallback (if yt-dlp still fails):** The `YouTubeTranscriptApi` accepts a custom `http_client` (requests.Session). Pass a session with Chrome cookies to bypass the IP block:
```python
import requests, browser_cookie3
session = requests.Session()
session.cookies = browser_cookie3.chrome(domain_name='.youtube.com')
api = YouTubeTranscriptApi(http_client=session)
```
This requires `pip install browser_cookie3` (not in current requirements.txt) and has the same Chrome encryption issues on macOS Chrome 127+.

### Pattern 7: Railway Health Check

**What:** Configure Railway to check `/health` endpoint before marking deployment live.

**Configuration via Railway Dashboard:**
- Service Settings → Health Check Path: `/health`
- Health Check Timeout: 300 seconds (default; init_db.sql on first deploy may need up to 60s)

**The `/health` endpoint is already implemented in `app/main.py`** (returns `{"status": "ok"}`).

**Note:** Railway performs health checks using the `PORT` variable. Since the container listens on `${PORT:-8000}` and Railway injects `PORT=8080`, the health check automatically uses port 8080. No extra configuration needed.

### Anti-Patterns to Avoid

- **Railway pgvector: using standard Postgres addon.** The standard Postgres addon does NOT include the `vector` extension. Deploy via the `pgvector/pgvector:pg17` marketplace template.
- **Alpine base image.** Alpine uses musl libc. `psycopg[binary]` ships manylinux wheels (glibc-based). Alpine requires compiling from source, needing `musl-dev postgresql-dev`. Use `python:3.12-slim` (Debian-based) instead.
- **Exec form CMD with `$PORT`.** Shell variables don't expand in JSON array CMD form. Always use shell form or a start.sh script.
- **`NEXT_PUBLIC_API_URL` vs runtime env:** All `NEXT_PUBLIC_` variables are inlined at build time. Changing them after deploy requires a Vercel redeploy. Server-side env vars (without `NEXT_PUBLIC_`) are available at runtime via `process.env` on the server but NOT in client-side code.
- **`docker-compose down -v`.** This deletes the `pgdata` named volume, destroying all 656+ corpus chunks. Must be prominently documented in `RUNNING.md`. Normal operation uses `docker-compose down` (no `-v`).
- **`--js-runtimes nodejs` flag.** This value is wrong. yt-dlp's `--js-runtimes` flag accepts `node`, `deno`, `bun`, `quickjs` — not `nodejs`. The existing code has this bug.
- **Committing API keys.** `.env` is already gitignored. Never use `git add .env` or store keys in `railway.json` or `vercel.json`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTPS/TLS for Railway service | nginx + certbot | Railway auto-provisioned subdomain | Railway provides `*.up.railway.app` with automatic TLS |
| HTTPS for Vercel frontend | reverse proxy | Vercel automatic | Vercel provisions TLS on `*.vercel.app` automatically |
| Schema migrations on startup | custom migration runner | `psql $DATABASE_URL -f init_db.sql` in start.sh | init_db.sql is already fully idempotent via `IF NOT EXISTS` |
| Cookie extraction from Chrome | custom DPAPI decryption | `yt-dlp --cookies-from-browser chrome` | yt-dlp handles Chrome's Keychain/DPAPI correctly on macOS |
| Database backup format | custom serializer | `pg_dump -F p` (plain SQL) | pg_dump + psql is the standard round-trip; no additional tooling |

**Key insight:** Railway's managed container approach means there is no OS-level infrastructure to configure. The app just needs to listen on `$PORT` and Railway handles everything else (TLS, load balancing, restarts).

---

## Runtime State Inventory

This is a migration/deployment phase, not a rename. The relevant runtime state to consider:

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | Local Docker Postgres: 656 chunks (21 forum, 625 pdf_manual, 10 web_article, 0 youtube) in `pgdata` Docker volume | pg_dump → psql restore to Railway after YouTube fix |
| Live service config | Railway service (new — not yet created); Vercel project (new — not yet created) | Create via Railway dashboard + Vercel dashboard |
| OS-registered state | None — no cron jobs, Task Scheduler tasks, or pm2 processes for this project | None |
| Secrets/env vars | `.env` at project root (gitignored): DATABASE_URL, OPENAI_API_KEY, ANTHROPIC_API_KEY | Set same keys as Railway env vars via dashboard; never commit |
| Build artifacts | `venv/` (Python 3.12); `frontend/.next/` (Next.js build output) — both gitignored | Dockerfile pip install handles venv; Vercel builds Next.js from source |

**YouTube corpus gap:** Currently 0 YouTube chunks in corpus. The corpus pre-seeded to Railway SHOULD include YouTube data. This requires fixing the yt-dlp issue first (Part A/B/C above), then re-running the pipeline and only then doing pg_dump.

---

## Common Pitfalls

### Pitfall 1: Standard Railway Postgres Addon Missing pgvector

**What goes wrong:** Deploying with Railway's default Postgres addon and running `CREATE EXTENSION vector` fails with "could not open extension control file: No such file or directory".

**Why it happens:** The standard Railway Postgres template uses the official `postgres` Docker image which does not include the `vector` extension binary.

**How to avoid:** Deploy specifically the **pgvector/pgvector:pg17** template from Railway's marketplace. This image has pgvector pre-installed at the OS level. `CREATE EXTENSION IF NOT EXISTS vector` then succeeds.

**Warning signs:** `init_db.sql` runs and fails on line 14 with extension error on Railway but works locally.

### Pitfall 2: `--js-runtimes nodejs` Flag Wrong Value

**What goes wrong:** yt-dlp silently falls back to "all runtimes unavailable" and cannot solve the YouTube n-challenge, causing subtitle download to fail with "Only images are available".

**Why it happens:** The correct flag value is `node` (not `nodejs`). The existing `app/ingest/loader.py` code has `"--js-runtimes", "nodejs"` which yt-dlp logs as `WARNING: Ignoring unsupported JavaScript runtime(s): nodejs`.

**How to avoid:** Remove the `--js-runtimes` flag entirely OR change it to `node`. After installing `yt-dlp[default]` (which includes `yt-dlp-ejs`), yt-dlp auto-detects the correct JS runtime.

**Warning signs:** yt-dlp logs `WARNING: Ignoring unsupported JavaScript runtime(s): nodejs` (seen in live test).

### Pitfall 3: yt-dlp n-Challenge Fails Even with Node in PATH

**What goes wrong:** yt-dlp shows `[debug] JS runtimes: none` even when `node --version` works in the same shell.

**Why it happens:** `yt-dlp-ejs` package is not installed. Without it, yt-dlp has no EJS challenge scripts to run even if a JavaScript runtime is available. The package must be installed separately (via `yt-dlp[default]` or `pip install yt-dlp-ejs`).

**How to avoid:** Add `yt-dlp[default]` to `requirements.txt` instead of bare `yt-dlp`. This installs `yt-dlp-ejs==0.8.0`, `brotli`, `mutagen`, and `pycryptodomex` as optional but needed extras.

**Warning signs:** `[debug] JS runtimes: none` in yt-dlp verbose output despite Node.js being installed.

### Pitfall 4: `NEXT_PUBLIC_API_URL` Not Set Before Vercel Build

**What goes wrong:** The Next.js rewrite destination is `http://localhost:8000` in production because the env var wasn't set before the build.

**Why it happens:** `NEXT_PUBLIC_` variables are inlined at build time. If the variable isn't set in Vercel's environment before the first build, it's missing from the JavaScript bundle.

**How to avoid:** Set `NEXT_PUBLIC_API_URL` in Vercel's environment variables (Dashboard → Settings → Environment Variables) **before** triggering the first deployment. After adding/changing the variable, trigger a manual redeploy.

**Warning signs:** Chat requests go to localhost:8000 from Vercel and fail with connection refused.

### Pitfall 5: `docker-compose down -v` Destroys Corpus

**What goes wrong:** All 656+ corpus chunks are lost. The `pgdata` Docker volume is deleted. Re-ingestion (with OpenAI API costs) is required.

**Why it happens:** The `-v` flag deletes named volumes. `docker-compose down` (without `-v`) is safe. This is a user error risk.

**How to avoid:** Document prominently in `RUNNING.md`. Never include `-v` in scripts or documentation unless explicitly describing "full reset" procedures.

**Warning signs:** `docker-compose up` after `down -v` shows 0 chunks in `chunks` table.

### Pitfall 6: pg_dump Plain Text Includes COPY Commands that Fail on Railway

**What goes wrong:** `pg_dump -F p` (plain text) includes `COPY` commands with `\\.` terminators. When restored via `psql`, these work fine. No issue.

**Alternative risk:** Using `pg_dump -F c` (custom binary) requires `pg_restore`, not `psql`. The custom format is more efficient but adds tooling complexity. For this corpus size (656 chunks), plain text is perfectly adequate.

**How to avoid:** Stick with `pg_dump -F p` + `psql < dump.sql`. Simpler restore, no additional tooling needed.

### Pitfall 7: Dockerfile WORKDIR and COPY Paths

**What goes wrong:** `scripts/init_db.sql` not found at runtime because WORKDIR is set but COPY paths are wrong.

**Why it happens:** `COPY app/ ./app/` copies the app directory. `COPY scripts/ ./scripts/` copies scripts. If `data/` (gear_aliases.json) is not copied, alias expansion fails.

**How to avoid:** Explicitly COPY all required directories: `app/`, `scripts/`, `data/`. The `raw_data/` directory (corpus source files) does NOT need to be in the production image — only the database (Railway Postgres) holds the processed corpus.

---

## Code Examples

Verified patterns from codebase reading and live tests:

### Exact yt-dlp fix for `_load_via_ytdlp()`

```python
# Source: live testing in this session (app/ingest/loader.py lines 425-440)
# Changes: ADD --cookies-from-browser chrome; REMOVE --js-runtimes nodejs
cmd = [
    "yt-dlp",
    "--cookies-from-browser", "chrome",  # NEW: bypasses IP block with authenticated session
    "--write-auto-subs",
    "--sub-lang", "en",
    "--sub-format", "vtt",
    "--skip-download",
    # REMOVED: "--js-runtimes", "nodejs",  ← was wrong; yt-dlp-ejs auto-detects runtime
    f"https://www.youtube.com/watch?v={video_id}",
    "-o", out_tmpl,
]
```

### pg_dump and restore commands

```bash
# Source: Railway blog (blog.railway.com/p/postgre-backup) + docker exec pattern
# Verified: pg_dump 17.10 available inside guitar-tone-advisor-db-1 container

# Dump from local Docker Postgres (plain text format for simple psql restore)
docker exec guitar-tone-advisor-db-1 \
  pg_dump -U postgres -d guitar_tone_advisor -F p \
  > corpus_dump.sql

# Install psql locally (if not present)
brew install libpq
export PATH="/opt/homebrew/opt/libpq/bin:$PATH"

# Restore to Railway (get DATABASE_PUBLIC_URL from Railway Variables tab)
export RAILWAY_DATABASE_PUBLIC_URL="postgresql://postgres:PASSWORD@HOST:PORT/railway"
psql "$RAILWAY_DATABASE_PUBLIC_URL" < corpus_dump.sql
```

### next.config.js env var update (D-05)

```javascript
// Source: direct reading of frontend/next.config.js
/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/py/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/:path*`,
      },
    ];
  },
};
module.exports = nextConfig;
```

### Minimal idempotent start.sh

```bash
#!/usr/bin/env bash
# Source: Railway FastAPI deployment pattern (docs.railway.com/guides/rag-pipeline-pgvector)
set -e
psql "$DATABASE_URL" -f scripts/init_db.sql
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
```

### RUNNING.md persistence section

```markdown
## ⚠️ Critical: Volume Persistence Warning

**NEVER run `docker-compose down -v`** — the `-v` flag deletes named Docker volumes,
including `pgdata` which stores all 656+ ingested corpus chunks. You would lose the
entire corpus and need to re-run the full ingestion pipeline (which costs OpenAI API
credits and takes significant time).

**Safe operations:**
- `docker-compose down` — stops containers, RETAINS corpus (pgdata volume persists)
- `docker-compose up -d` — starts containers, uses existing pgdata volume
- `docker-compose restart` — safe restart, no data loss

**To verify corpus integrity after restart:**
```bash
docker-compose up -d
psql "$DATABASE_URL" -c "SELECT source_type, count(*) FROM chunks GROUP BY source_type;"
```
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `get_transcript()` (static method) | `YouTubeTranscriptApi().fetch()` (instance method) | youtube-transcript-api v1.x | Already correct in codebase |
| `--js-runtimes nodejs` | `--js-runtimes node` or omit (EJS auto-detects) | yt-dlp EJS system (2025) | Bug in current loader.py — must fix |
| bare `yt-dlp` in requirements.txt | `yt-dlp[default]` | yt-dlp EJS system (2025) | Installs `yt-dlp-ejs` for n-challenge solving |
| Hardcoded `localhost:8000` in next.config.js | `process.env.NEXT_PUBLIC_API_URL \|\| 'localhost:8000'` | Phase 7 (this phase) | Required for production Vercel deploy |

**Deprecated/outdated:**
- `tiangolo/uvicorn-gunicorn-fastapi` Docker image: no longer recommended by FastAPI docs. Build your own image from `python:3.12-slim`.
- `psycopg2-binary`: This project uses psycopg v3 (`psycopg[binary]`), not v2. The v2 package is `psycopg2-binary`. Don't confuse them.
- `--js-runtimes nodejs` flag value: wrong. Use `node` or omit.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Railway pgvector/pgvector:pg17 template provides `DATABASE_URL` and `DATABASE_PUBLIC_URL` env vars | Architecture | If variable names differ, start.sh psql command fails; check Railway Variables tab |
| A2 | Railway `PORT` is always 8080 at runtime | Standard Stack | If PORT differs, uvicorn won't bind to the right port; verify after first deploy |
| A3 | yt-dlp Chrome cookie extraction works on macOS with standard Chrome after the n-challenge fix | yt-dlp Fix | Verified cookies extract (3,287+ cookies); n-challenge fix still needs live end-to-end test with YouTube videos |
| A4 | `pip install "yt-dlp[default]"` in requirements.txt is valid pip extras syntax | Standard Stack | If `[default]` extras fail in pip, install `yt-dlp-ejs` explicitly as a separate line |
| A5 | Railway's pgvector/pgvector:pg17 container connects to the same postgres wire protocol for pg_restore | pg_dump/restore | Should be standard; verify after restore by checking chunk counts |

---

## Open Questions

1. **YouTube corpus after fix: will all 13 videos succeed?**
   - What we know: Chrome cookies extract successfully; EJS n-challenge fix (yt-dlp[default] + removing wrong --js-runtimes flag) should resolve the "JS runtimes: none" issue.
   - What's unclear: Some videos may be geo-blocked or have transcripts disabled regardless of authentication. `youtube-transcript-api` primary path is IP-blocked on this machine/network.
   - Recommendation: After applying the fix, run a test with 2-3 video IDs before the full pipeline. Accept partial success (some videos may still fail with auth-independent blocks).

2. **Railway pgvector template version: pg17 or pg18?**
   - What we know: Local dev uses `pgvector/pgvector:pg17`. Railway has both pg17 and pg18 templates.
   - What's unclear: Whether the pg_dump from pg17 restores cleanly into pg18.
   - Recommendation: Use the Railway `pgvector/pgvector:pg17` template to match the local Docker image.

3. **psql client for local pg_dump restore: Homebrew install required?**
   - What we know: `psql` is not in PATH locally (verified). `pg_dump` is only available inside the Docker container. `brew install libpq` is available.
   - What's unclear: Whether the user prefers psql via Homebrew or an alternative approach.
   - Recommendation: Install `libpq` via Homebrew for local psql. Alternative: use `docker run postgres:17 psql ...` if Homebrew is undesirable.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker | Local Postgres (pgdata volume) | ✓ | 29.4.3 | — |
| Local Postgres container | pg_dump corpus export | ✓ | pgvector/pgvector:pg17 (healthy) | — |
| yt-dlp (venv) | YouTube transcript ingestion | ✓ | 2026.3.17 | — |
| yt-dlp-ejs | EJS n-challenge solving | ✗ (not in requirements.txt) | 0.8.0 (installable) | Add to requirements.txt as `yt-dlp[default]` |
| Node.js >= 20 | yt-dlp EJS challenge | ✓ (via nvm) | 22.17.0 at `~/.nvm/versions/node/v22.17.0/bin/` | Needs to be in PATH when pipeline runs |
| Google Chrome | `--cookies-from-browser chrome` | ✓ | Standard macOS install | Firefox (if Chrome fails); cookies.txt file export |
| psql client (local) | pg_dump restore to Railway | ✗ (not in PATH) | — | `brew install libpq`; or use docker run postgres:17 |
| Railway CLI | Optional deployment automation | ✗ | — | Dashboard-based deployment (fine for one-time) |
| Vercel CLI | Optional deployment automation | ✗ | — | Dashboard-based deployment (fine for one-time) |

**Missing dependencies with no fallback:**
- None — all blockers have fallbacks or simple install paths.

**Missing dependencies with fallback:**
- `yt-dlp-ejs`: install via `yt-dlp[default]` in requirements.txt — required before full pipeline run.
- `psql` (local): install via `brew install libpq` — required for corpus restore to Railway.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.5.0 |
| Config file | `/Users/yashvinaykumar/Desktop/guitar-tone-advisor/pytest.ini` |
| Quick run command | `venv/bin/python -m pytest tests/ -x -q --ignore=tests/test_eval_ragas.py` |
| Full suite command | `venv/bin/python -m pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PERSIST-01 | `pgdata` volume survives `down`/`up` | manual | `docker exec ... psql ... SELECT COUNT(*) FROM chunks;` | N/A (manual verification) |
| DEPLOY-01 | Dockerfile builds successfully | smoke | `docker build -t guitar-tone-advisor . && docker run --rm -e DATABASE_URL=... guitar-tone-advisor python -c "import app.main"` | ❌ Wave 0: no Dockerfile yet |
| DEPLOY-02 | `/health` returns 200 over HTTPS | smoke | `curl https://<railway-url>/health` | N/A (manual after deploy) |
| DEPLOY-03 | API keys in env vars, not repo | static | `git grep -rn "sk-ant\|sk-proj" app/ scripts/ Dockerfile` | N/A (static check) |
| DEPLOY-04 | Corpus pre-seeded: chunk count matches | smoke | `psql $RAILWAY_DATABASE_PUBLIC_URL -c "SELECT COUNT(*) FROM chunks;"` | N/A (manual after restore) |
| DEPLOY-05 | Vercel rewrite proxies to Railway | smoke | `curl https://<vercel-url>/api/py/health` | N/A (manual after deploy) |

**Note on test automation:** Most Phase 7 requirements involve infrastructure state (deployed containers, external URLs) rather than code logic. The existing 144-test suite should continue to pass unchanged. The deployment verification is inherently manual-smoke-test oriented.

### Wave 0 Gaps

- No new test files needed: existing suite (`tests/`) does not need changes for Phase 7 infrastructure work.
- Verification steps are documented as manual smoke commands (see above).

*(Existing test infrastructure covers all code-level requirements; Phase 7 adds no new Python logic requiring new unit tests.)*

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No auth in this project (single-user, local tool) |
| V3 Session Management | No | In-process session dict; not a deployment concern |
| V4 Access Control | No | No multi-user access control |
| V5 Input Validation | Yes (existing) | `message_not_empty_or_too_long` validator in ChatRequest; `_VIDEO_ID_RE` in loader.py |
| V6 Cryptography | No | No encryption hand-rolled; TLS handled by Railway/Vercel automatically |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| API keys in environment variables on Railway | Information Disclosure | Railway encrypts env vars at rest; only visible to authorized project members. Never commit to git. Already enforced by `.gitignore`. |
| pg_dump corpus_dump.sql exposure | Information Disclosure | corpus_dump.sql contains all user-ingested corpus text. Add `corpus_dump.sql` to `.gitignore` before running pg_dump. |
| `--cookies-from-browser chrome` cookies exposure | Information Disclosure | yt-dlp reads cookies from local Chrome profile. Cookies are passed to YouTube only. Not logged or persisted by yt-dlp beyond the subprocess lifetime. |
| Railway PostgreSQL external access | Elevation of Privilege | Railway uses TCP proxy with authenticated `DATABASE_PUBLIC_URL`. The default Railway Postgres has no public access without the TCP proxy enabled. |

**Security note on corpus_dump.sql:** The pg_dump output contains all corpus text (forum posts, manual content, article text). This is not sensitive, but the file should be kept local (not committed to git) and deleted after the Railway restore is confirmed.

---

## Sources

### Primary (HIGH confidence)

- Direct codebase reading — `app/ingest/loader.py`, `scripts/init_db.sql`, `app/config.py`, `app/main.py`, `frontend/next.config.js`, `docker-compose.yml` — all files read in this session
- Live tool invocations:
  - `docker exec guitar-tone-advisor-db-1 psql ...` → 656 chunks confirmed, no YouTube chunks
  - `venv/bin/yt-dlp -v --cookies-from-browser chrome ...` → confirmed cookie extraction (3,287 cookies); confirmed `[debug] JS runtimes: none` root cause; confirmed `WARNING: Ignoring unsupported JavaScript runtime(s): nodejs` bug
  - `pip install "yt-dlp[default]"` → `yt-dlp-ejs==0.8.0` installed successfully
  - `docker exec guitar-tone-advisor-db-1 pg_dump --version` → pg_dump 17.10 available inside container
  - `npm view next version` → 16.2.7 (registry latest)
  - `pypi psycopg-binary` page → 3.3.4 manylinux wheels confirmed
- `scripts/init_db.sql` grep → all DDL already uses `IF NOT EXISTS` (already idempotent — no changes needed)

### Secondary (MEDIUM confidence)

- [Railway Docs: RAG Pipeline with pgvector](https://docs.railway.com/guides/rag-pipeline-pgvector) — `uvicorn app:app --host 0.0.0.0 --port $PORT` pattern confirmed
- [Railway Docs: Health Checks](https://docs.railway.com/reference/healthchecks) — PORT variable used for health check; `/health` path configurable in service settings
- [Railway Help Station: pgvector setup](https://station.railway.com/questions/setting-up-pgvector-postgresql-db-e6631a7d) — pgvector template required (not standard Postgres); `CREATE EXTENSION IF NOT EXISTS vector` works after deploying template
- [Railway Blog: PostgreSQL Backup](https://blog.railway.com/p/postgre-backup) — `pg_dump` with `DATABASE_PUBLIC_URL`; `DATABASE_PUBLIC_URL` vs `DATABASE_URL` distinction confirmed
- [yt-dlp EJS Wiki](https://github.com/yt-dlp/yt-dlp/wiki/EJS) — EJS system requires `yt-dlp-ejs` package + JS runtime >= 20
- [psycopg-binary PyPI](https://pypi.org/project/psycopg-binary/) — manylinux wheels for Python 3.10-3.14 confirmed, no build tools needed
- [Vercel docs: Root Directory for monorepos](https://vercel.com/docs/monorepos) — Dashboard Root Directory setting required for `frontend/` subfolder deployment

### Tertiary (LOW confidence — flagged in Assumptions Log)

- [Railway community: PORT=8080 at runtime](https://station.railway.com/questions/service-fails-to-deploy-not-receiving-1198a4e3) — PORT value of 8080 mentioned in community discussion [A2 in Assumptions Log]
- [DEV Community: yt-dlp Docker EJS fix](https://dev.to/nareshipme/fixing-yt-dlp-in-docker-n-challenge-ejs-scripts-deno-2x-and-the-playerclientios-cookie-trap-54d6) — referenced for Deno 2.x as alternative to Node for EJS challenge

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions verified via pip index, npm view, live package installs
- Architecture (Dockerfile, start.sh, Railway config): HIGH — verified via Railway docs + FastAPI official Docker guide + live yt-dlp testing
- yt-dlp fix: HIGH — root causes identified via live debug session; fix is a 2-line code change + requirements.txt update
- pg_dump/restore commands: MEDIUM — pg_dump via docker exec verified; psql restore to Railway DATABASE_PUBLIC_URL follows documented Railway pattern but not live-tested against Railway
- Vercel deployment: MEDIUM — standard Next.js subfolder deployment; well-documented pattern

**Research date:** 2026-06-02
**Valid until:** 2026-07-02 (Railway/Vercel platform; yt-dlp changes frequently — re-verify yt-dlp cookie behavior if more than 30 days pass)
