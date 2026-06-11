---
phase: 07-persistent-corpus-cloud-deployment
plan: 03
subsystem: infra
tags: [railway, vercel, deployment, corpus-restore, docker, pgvector]

key-files:
  created:
    - scripts/start.sh (already existed — psql init_db.sql + uvicorn entrypoint)
    - Dockerfile (added postgresql-client apt install for psql availability)
  referenced:
    - corpus_dump.sql (local-only, gitignored, deleted after restore)

requirements-satisfied: [PERSIST-01, DEPLOY-01, DEPLOY-02, DEPLOY-03, DEPLOY-04, DEPLOY-05]

self-check: PASSED
---

## What Was Built

Operator-driven deployment workflow executed end-to-end: full corpus regenerated locally (including YouTube), Docker persistence verified, corpus transferred to Railway, FastAPI backend deployed, and Next.js frontend deployed to Vercel with a live cited-answer smoke test.

## Tasks Completed

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Full corpus pipeline with YouTube fix | ✓ | 785 chunks total; 2 YouTube IDs blocked (1KzmG9Hb8PI, TJTQID5J72A), remainder ingested; recall@8 ≥ 1.0 |
| 2 | Docker persistence verified + pg_dump | ✓ | 785 chunks before and after `docker-compose down/up` (no -v); 3 COPY blocks in dump |
| 3 | Railway provisioning + corpus restore + health check | ✓ | pgvector/pg17 template; Dockerfile fix (postgresql-client); 785 chunks restored; `/health` → `{"status":"ok"}` |
| 4 | Vercel frontend deploy + E2E smoke test | ✓ | Root Directory=frontend; NEXT_PUBLIC_API_URL set pre-build; `/api/py/health` proxies correctly; cited answer confirmed |

## Deviations

- **Dockerfile needed `postgresql-client`**: `python:3.12-slim` does not include `psql`; `scripts/start.sh` calls `psql` to run `init_db.sql`. Added `apt-get install -y postgresql-client` to Dockerfile (commit `f313764`).
- **corpus_dump.sql restore ordering**: plain pg_dump ordered `chunks` COPY before `documents` COPY, causing FK constraint violations on first restore. Resolved by truncating tables and piping only the chunks COPY block (lines 132–918) after documents loaded successfully.
- **Railway builder stall**: AWS us-west1 incident caused ~24-min build queue stall. Resolved by switching Railway region to EU West.
- **`DATABASE_URL` misconfigured**: initial value was `postgresql://localhost:5432/guitar_tone_advisor` (local Docker URL). Updated to `${{pgvector.DATABASE_URL}}` Railway reference variable.
- **2 YouTube IDs blocked**: `1KzmG9Hb8PI` and `TJTQID5J72A` returned no transcripts. Partial success accepted per plan spec; can retry later.

## Verification Results

| Check | Result |
|-------|--------|
| `docker build` exits 0 | ✓ PASS (DEPLOY-01) |
| Docker persistence (785 chunks survive down/up) | ✓ PASS (PERSIST-01) |
| `curl https://guitar-tone-advisor-production.up.railway.app/health` | ✓ `{"status":"ok"}` (DEPLOY-02) |
| Restored chunk count matches local dump (785) | ✓ PASS (DEPLOY-04) |
| `git grep -rn "sk-ant\|sk-proj"` — no key literals | ✓ PASS (DEPLOY-03) |
| `curl https://guitar-tone-advisor.vercel.app/api/py/health` | ✓ `{"status":"ok"}` (DEPLOY-05) |
| Browser E2E: tone question → cited streamed answer | ✓ PASS |

## Live URLs

- **Backend:** https://guitar-tone-advisor-production.up.railway.app
- **Frontend:** https://guitar-tone-advisor.vercel.app
