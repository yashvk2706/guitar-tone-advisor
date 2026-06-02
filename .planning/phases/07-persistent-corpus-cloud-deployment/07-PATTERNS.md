# Phase 7: Persistent Corpus & Cloud Deployment - Pattern Map

**Mapped:** 2026-06-02
**Files analyzed:** 6 (2 new, 1 new doc, 3 modify)
**Analogs found:** 4 / 6 (2 new infra files have no codebase analog — use RESEARCH.md patterns)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `Dockerfile` (NEW) | config | request-response | `docker-compose.yml` (structure reference only) | partial |
| `scripts/start.sh` (NEW) | config/utility | request-response | `scripts/init_db.sql` (same scripts/ directory context) | partial |
| `RUNNING.md` (NEW) | config/doc | n/a | `README.md` (project root doc pattern) | partial |
| `app/ingest/loader.py` (MODIFY) | utility | batch/transform | self (existing file — targeted 2-line fix) | exact |
| `requirements.txt` (MODIFY) | config | n/a | self (existing file — single token change) | exact |
| `frontend/next.config.js` (MODIFY) | config | request-response | self (existing file — single string substitution) | exact |

---

## Pattern Assignments

### `Dockerfile` (NEW — config, request-response)

**Analog:** `docker-compose.yml` provides the pgvector image reference and service structure. No Dockerfile exists in the codebase — use the RESEARCH.md verified pattern directly.

**Base image and structure pattern** (from RESEARCH.md Pattern 1, verified against psycopg-binary PyPI manylinux wheel support):
```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY scripts/ ./scripts/
COPY data/ ./data/

RUN chmod +x scripts/start.sh

CMD ["scripts/start.sh"]
```

**Critical constraints:**
- Base image MUST be `python:3.12-slim` (Debian-based) — NOT Alpine. Alpine uses musl libc; `psycopg[binary]` ships manylinux (glibc) wheels and will not run.
- `COPY data/ ./data/` is required — `data/gear_aliases.json` is read at runtime by the alias expansion code.
- `raw_data/` must NOT be copied — corpus lives in Railway Postgres, not the container filesystem.
- `CMD ["scripts/start.sh"]` (exec form calling a shell script) is the correct pattern. Do NOT use exec form with `$PORT` directly — shell variables do not expand in JSON array CMD form.
- No `apt-get` installs needed: `psycopg[binary]` and `yt-dlp[default]` both install via manylinux/wheel with no build toolchain.

**docker-compose.yml reference** (`/Users/yashvinaykumar/Desktop/guitar-tone-advisor/docker-compose.yml` lines 1-5) — confirms the pgvector image tag to match locally:
```yaml
services:
  db:
    image: pgvector/pgvector:pg17
```
Railway Postgres must use the same `pgvector/pgvector:pg17` template (not the standard Postgres addon, which lacks the `vector` extension binary).

---

### `scripts/start.sh` (NEW — config/utility, request-response)

**Analog:** No shell scripts exist in the codebase. Pattern sourced from RESEARCH.md Pattern 2 (Railway FastAPI deployment guide, verified).

**Full file content** (from RESEARCH.md Pattern 2):
```bash
#!/usr/bin/env bash
# Source: Railway FastAPI deployment pattern
set -e

echo "Running schema initialization..."
psql "$DATABASE_URL" -f scripts/init_db.sql

echo "Starting uvicorn on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
```

**Critical constraints:**
- `set -e` — if `psql` fails (e.g., extension not found), container startup aborts and Railway marks the deployment failed. This is correct behavior.
- `exec` prefix on uvicorn — replaces the bash process so uvicorn receives SIGTERM directly for graceful shutdown.
- `${PORT:-8000}` — Railway injects `PORT=8080` at runtime; the fallback `8000` preserves local `docker run` behavior.
- `psql "$DATABASE_URL"` — Railway provides `DATABASE_URL` as an env var pointing to the internal Railway Postgres network. The `scripts/init_db.sql` is already fully idempotent (all DDL uses `IF NOT EXISTS` — confirmed by reading the file; no changes to `init_db.sql` are needed).

**init_db.sql idempotency confirmed** (`/Users/yashvinaykumar/Desktop/guitar-tone-advisor/scripts/init_db.sql` lines 12-87) — every DDL statement uses `IF NOT EXISTS`:
```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS documents ( ... );
CREATE TABLE IF NOT EXISTS chunks ( ... );
CREATE TABLE IF NOT EXISTS ingest_runs ( ... );
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_cos ...;
```
No changes to `init_db.sql` are required.

---

### `RUNNING.md` (NEW — documentation)

**Analog:** No project-root warning docs exist. `README.md` exists at project root but its structure is generic Next.js boilerplate.

**Content pattern** (from RESEARCH.md Pattern — RUNNING.md persistence section, decision D-15):

The file must include:
1. A prominent `## Critical: Volume Persistence Warning` section warning against `docker-compose down -v`
2. A "Safe operations" table showing `down` vs `down -v` behavior
3. A corpus integrity verification command
4. Local dev startup instructions (for completeness)

**Core warning block to include verbatim:**
```markdown
## Critical: Volume Persistence Warning

**NEVER run `docker-compose down -v`** — the `-v` flag deletes named Docker volumes,
including `pgdata` which stores all ingested corpus chunks. You would lose the entire
corpus and need to re-run the full ingestion pipeline (OpenAI API costs + time).

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

### `app/ingest/loader.py` (MODIFY — utility, batch/transform)

**Analog:** Self — targeted fix to the `_load_via_ytdlp()` function.

**Current state** (`/Users/yashvinaykumar/Desktop/guitar-tone-advisor/app/ingest/loader.py` lines 426-435):
```python
cmd = [
    "yt-dlp",
    "--write-auto-subs",
    "--sub-lang", "en",
    "--sub-format", "vtt",
    "--skip-download",
    "--js-runtimes", "nodejs",  # yt-dlp defaults to deno; use node if present
    f"https://www.youtube.com/watch?v={video_id}",
    "-o", out_tmpl,
]
```

**Required change** — two edits to the `cmd` list:
1. ADD `"--cookies-from-browser", "chrome",` immediately after `"yt-dlp",` (line 427 insert)
2. REMOVE the two-element `"--js-runtimes", "nodejs",` entry (line 432 delete)

**Target state** (lines 426-435 after fix):
```python
cmd = [
    "yt-dlp",
    "--cookies-from-browser", "chrome",  # bypasses YouTube IP block with authenticated session
    "--write-auto-subs",
    "--sub-lang", "en",
    "--sub-format", "vtt",
    "--skip-download",
    # --js-runtimes nodejs removed: "nodejs" is wrong value; yt-dlp[default] auto-detects runtime
    f"https://www.youtube.com/watch?v={video_id}",
    "-o", out_tmpl,
]
```

**Why:** `--js-runtimes nodejs` emits `WARNING: Ignoring unsupported JavaScript runtime(s): nodejs` — the correct value is `node`, but omitting the flag entirely is cleaner since `yt-dlp[default]` (which installs `yt-dlp-ejs==0.8.0`) auto-detects the available JS runtime. `--cookies-from-browser chrome` was confirmed to extract 3,287+ cookies from local Chrome on macOS, bypassing the YouTube IP block that causes `RequestBlocked` on the primary `youtube-transcript-api` path.

**Surrounding context preserved:** All other lines in `_load_via_ytdlp()` (lines 401-476) remain unchanged — `subprocess.run`, VTT parsing, error handling, `RawDocument` construction.

---

### `requirements.txt` (MODIFY — config)

**Analog:** Self — single token substitution.

**Current state** (`/Users/yashvinaykumar/Desktop/guitar-tone-advisor/requirements.txt` line 23):
```
yt-dlp
```

**Required change** — replace bare `yt-dlp` with extras-enabled form:
```
yt-dlp[default]
```

**Why:** `yt-dlp[default]` installs `yt-dlp-ejs==0.8.0` as an optional extra. Without this package, yt-dlp logs `[debug] JS runtimes: none` even when Node.js >= 20 is in PATH — the EJS n-challenge solver scripts are simply absent. With `yt-dlp-ejs` installed and Node.js >= 20 in PATH, yt-dlp can solve the YouTube n-challenge and download subtitles.

**Full surrounding context** (lines 19-23 of requirements.txt — only line 23 changes):
```
pymupdf4llm==0.0.25
pypdf==5.9.0
youtube-transcript-api==1.2.4
yt-dlp[default]       ← was: yt-dlp
trafilatura==2.0.0
```

Note: No version pin on `yt-dlp[default]` — consistent with the existing unpinned `yt-dlp`. Current venv version is `2026.3.17`.

---

### `frontend/next.config.js` (MODIFY — config, request-response)

**Analog:** Self — single string substitution.

**Current state** (`/Users/yashvinaykumar/Desktop/guitar-tone-advisor/frontend/next.config.js` lines 1-12):
```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/py/:path*',
        destination: 'http://localhost:8000/:path*',
      },
    ];
  },
};
module.exports = nextConfig;
```

**Required change** — replace the hardcoded `'http://localhost:8000'` with an env var with localhost fallback (decision D-05):
```javascript
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

**Key change:** `'http://localhost:8000/:path*'` (string literal) → template literal using `process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'`.

**Why it works locally unchanged:** When `NEXT_PUBLIC_API_URL` is not set (local dev), the `||` fallback evaluates to `'http://localhost:8000'` — identical to the current behavior.

**Critical gotcha:** `NEXT_PUBLIC_API_URL` is a build-time variable (inlined into the JS bundle at `next build`). It must be set in Vercel's Environment Variables dashboard **before** the first Vercel deployment triggers. Changing it after deployment requires a Vercel redeploy.

---

## Shared Patterns

### Environment Variable Pattern
**Source:** `/Users/yashvinaykumar/Desktop/guitar-tone-advisor/app/config.py` (pydantic-settings)
**Apply to:** `Dockerfile` and `scripts/start.sh`

Railway injects env vars as process environment — `pydantic-settings` picks them up automatically from `os.environ`. No code changes needed in `app/config.py`. The `DATABASE_URL`, `OPENAI_API_KEY`, and `ANTHROPIC_API_KEY` fields in `Settings` already read from env. The Dockerfile must NOT hardcode any secret values; all secrets arrive via Railway's dashboard env var injection at container startup.

### Idempotent Schema Init Pattern
**Source:** `/Users/yashvinaykumar/Desktop/guitar-tone-advisor/scripts/init_db.sql` lines 1-87
**Apply to:** `scripts/start.sh`

Every DDL statement in `init_db.sql` already uses `IF NOT EXISTS`. This makes `psql "$DATABASE_URL" -f scripts/init_db.sql` safe to run on every container start (re-deploys, restarts). No guard logic needed in `start.sh` beyond `set -e`.

### Docker Volume Persistence Pattern
**Source:** `/Users/yashvinaykumar/Desktop/guitar-tone-advisor/docker-compose.yml` lines 18-19
**Apply to:** `RUNNING.md`

```yaml
volumes:
  pgdata:
```
The `pgdata` named volume is declared at the top level in `docker-compose.yml`. Named volumes survive `docker-compose down`. Only `docker-compose down -v` (or explicit `docker volume rm`) destroys them. This is the core fact that `RUNNING.md` must document.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `Dockerfile` | config | request-response | No Dockerfile exists in this codebase. Use RESEARCH.md Pattern 1 directly. |
| `scripts/start.sh` | config/utility | request-response | No shell scripts exist in `scripts/` (only `init_db.sql`). Use RESEARCH.md Pattern 2 directly. |

---

## Metadata

**Analog search scope:** Project root, `app/`, `scripts/`, `frontend/`
**Files read:** `docker-compose.yml`, `scripts/init_db.sql`, `app/ingest/loader.py` (lines 1-50, 418-476), `app/main.py` (lines 1-30), `requirements.txt`, `frontend/next.config.js`
**Pattern extraction date:** 2026-06-02
