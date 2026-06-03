---
phase: 07-persistent-corpus-cloud-deployment
plan: 02
subsystem: infra
tags: [docker, railway, vercel, deployment, next.js]

requires:
  - phase: 01-schema-forum-ingestion-golden-eval-set
    provides: scripts/init_db.sql idempotent schema DDL
  - phase: 06-full-corpus-ingestion
    provides: app/ and data/gear_aliases.json that get COPYed into image

provides:
  - Dockerfile (python:3.12-slim single-stage; COPYs app/ scripts/ data/; CMD scripts/start.sh)
  - scripts/start.sh (idempotent schema init + exec uvicorn on ${PORT:-8000})
  - frontend/next.config.js env-var-driven rewrite with localhost fallback
  - .gitignore rule for corpus_dump.sql
  - RUNNING.md with volume persistence warning and local dev docs

affects: [07-persistent-corpus-cloud-deployment]

tech-stack:
  added: []
  patterns:
    - "Single-stage python:3.12-slim Dockerfile (psycopg[binary] glibc manylinux wheel constraint)"
    - "start.sh wrapper: set -e, idempotent psql init, exec uvicorn on ${PORT:-8000}"
    - "NEXT_PUBLIC_API_URL || localhost fallback in next.config.js rewrites"

key-files:
  created:
    - Dockerfile
    - scripts/start.sh
    - RUNNING.md
  modified:
    - frontend/next.config.js
    - .gitignore

key-decisions:
  - "python:3.12-slim NOT alpine — psycopg[binary] ships manylinux (glibc) wheels incompatible with musl"
  - "CMD ['scripts/start.sh'] exec-form shell-script pattern — shell vars don't expand in JSON-array CMD"
  - "exec uvicorn replaces bash process so uvicorn receives SIGTERM for graceful shutdown"
  - "NEXT_PUBLIC_API_URL is build-time inlined by Vercel — must be set before first deploy"
  - "corpus_dump.sql gitignored before any pg_dump runs to prevent corpus text commit"

patterns-established:
  - "Docker startup pattern: psql schema-init → exec uvicorn (idempotent, set -e abort on failure)"
  - "No secrets in image: DATABASE_URL/OPENAI_API_KEY/ANTHROPIC_API_KEY via Railway env injection"

requirements-completed: [DEPLOY-01, DEPLOY-03, DEPLOY-05, PERSIST-01]

duration: 15min
completed: 2026-06-02
---

# Phase 7 Plan 02: Deployment Infrastructure Summary

**Dockerfile (python:3.12-slim), scripts/start.sh (schema-init + exec uvicorn), env-var-driven next.config.js rewrite, corpus_dump.sql gitignore, and RUNNING.md volume-persistence warning**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-06-02
- **Completed:** 2026-06-02
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- `Dockerfile`: single-stage `python:3.12-slim`, COPY requirements → pip install → COPY app/ scripts/ data/, `CMD ["scripts/start.sh"]`
- `scripts/start.sh`: `set -e`, `psql "$DATABASE_URL" -f scripts/init_db.sql` (idempotent), `exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"`
- `frontend/next.config.js`: destination changed to template literal `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/:path*` — local dev unchanged
- `.gitignore`: `corpus_dump.sql` added (pg_dump artifact must never be committed)
- `RUNNING.md`: prominent `⚠️ Critical: Volume Persistence Warning` section, safe-ops table, corpus integrity query, local dev startup sequence

## Task Commits

1. **Task 1: Create Dockerfile and scripts/start.sh** - `a7a46c1` (feat)
2. **Task 2: Update next.config.js rewrite to NEXT_PUBLIC_API_URL** - `f6b0672` (feat)
3. **Task 3: Add corpus_dump.sql gitignore + write RUNNING.md** - `35f5949` (docs)

## Files Created/Modified
- `Dockerfile` — Single-stage python:3.12-slim image for Railway deployment
- `scripts/start.sh` — Startup wrapper: idempotent schema init then exec uvicorn
- `frontend/next.config.js` — Env-var-driven rewrite destination with localhost fallback
- `.gitignore` — Added corpus_dump.sql rule with explanatory comment
- `RUNNING.md` — Volume persistence warning, safe ops table, verification query, local dev docs

## Decisions Made
- **python:3.12-slim over alpine:** Alpine uses musl libc; `psycopg[binary]` manylinux wheels won't run on it. No `apt-get` needed — all deps install from wheels.
- **CMD exec-form calling shell script:** `CMD ["scripts/start.sh"]` — JSON array exec-form calls the shell script, which can then use `${PORT:-8000}` shell expansion. Direct JSON-array uvicorn with `$PORT` would not expand the variable.
- **`exec` prefix on uvicorn:** Replaces bash PID so uvicorn receives SIGTERM directly for Railway's graceful shutdown.
- **`set -e`:** Any psql init failure aborts startup; Railway marks the deployment failed rather than silently serving against a broken schema.
- **No secrets in image:** `DATABASE_URL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` arrive via Railway dashboard env var injection at runtime only.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

Plan 03 (human checkpoint) documents all Railway and Vercel configuration steps — credentials are never committed to the repo.

## Next Phase Readiness

- All infrastructure files exist; Plan 03 operator can now build (`docker build -t guitar-tone-advisor .`) and deploy without writing any config by hand
- `next.config.js` rewrite ready for `NEXT_PUBLIC_API_URL` Vercel env var (must be set before first Vercel build)
- `RUNNING.md` documents the persistence guarantee for the persistence-verify step in Plan 03 Task 2

## Self-Check: PASSED

### Acceptance Criteria Verification

**Task 1 (DOCKER_OK):**
- `FROM python:3.12-slim`: PASS
- `COPY data/`: PASS
- No `alpine` or `apt-get`: PASS
- CMD references `scripts/start.sh`: PASS
- `set -e` in start.sh: PASS
- `init_db.sql` in start.sh: PASS
- `exec uvicorn` in start.sh: PASS
- `${PORT:-8000}` in start.sh: PASS
- `git grep -nE "sk-ant|sk-proj"` over both files: no matches — PASS

**Task 2 (NEXTCFG_OK):**
- `process.env.NEXT_PUBLIC_API_URL` in next.config.js: PASS
- `|| 'http://localhost:8000'` fallback: PASS
- `source: '/api/py/:path*'` preserved: PASS
- `module.exports = nextConfig` preserved: PASS
- Hardcoded `destination: 'http://localhost:8000/:path*'` removed: PASS

**Task 3 (DOCS_OK):**
- `corpus_dump.sql` in .gitignore: PASS
- `docker-compose down -v` in RUNNING.md: PASS
- `pgdata` in RUNNING.md: PASS
- `⚠` warning glyph in RUNNING.md: PASS
- `GROUP BY source_type` query in RUNNING.md: PASS

---
*Phase: 07-persistent-corpus-cloud-deployment*
*Completed: 2026-06-02*
