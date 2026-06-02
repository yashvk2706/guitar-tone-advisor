# Phase 7: Persistent Corpus & Cloud Deployment - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-02
**Phase:** 07-persistent-corpus-cloud-deployment
**Areas discussed:** AWS compute target, Frontend hosting, Corpus pre-seeding, HTTPS / ingress layer, CORS & API call routing, Railway Postgres pgvector setup, Dockerfile for FastAPI

---

## AWS Compute Target

| Option | Description | Selected |
|--------|-------------|----------|
| Same EC2 instance | Run pgvector Docker on same EC2 as FastAPI; pgdata volume on EBS | |
| RDS with pgvector | Managed Postgres on RDS; costs ~$15-30/mo | |
| **Railway (pivot)** | User selected "Skip AWS deployment. Use Railway instead — supports pgvector natively, deploys from GitHub automatically, free for personal projects" | ✓ |

**User's choice:** Railway instead of AWS — entire AWS discussion replaced by Railway platform decision.
**Notes:** Covers FastAPI backend as Railway service + Railway managed Postgres addon. ROADMAP's AWS EC2 intent is overridden by this decision.

---

## Frontend Hosting

| Option | Description | Selected |
|--------|-------------|----------|
| Railway service (same project) | Next.js as second Railway service; single dashboard | |
| **Vercel** | Free tier, native Next.js support, instant preview deploys | ✓ |

**User's choice:** Vercel for Next.js.

### Rewrite URL parameterization

| Option | Description | Selected |
|--------|-------------|----------|
| **NEXT_PUBLIC_API_URL env var** | `process.env.NEXT_PUBLIC_API_URL \|\| 'http://localhost:8000'` in next.config.js | ✓ |

**Notes:** Local dev unchanged. Vercel env var set to Railway FastAPI public URL.

---

## Corpus Pre-seeding

### YouTube bot-detection fix

| Option | Description | Selected |
|--------|-------------|----------|
| **Fix in Phase 7** | `--cookies-from-browser chrome` on yt-dlp fallback; run full pipeline locally first | ✓ |
| Skip YouTube for v1 | Deploy partial corpus (forum + PDFs + articles); YouTube as future task | |

**User's choice:** Fix as part of Phase 7 before deploying.

### Seeding method

| Option | Description | Selected |
|--------|-------------|----------|
| **pg_dump → restore** | pg_dump local Docker DB after full pipeline; restore to Railway Postgres | ✓ |
| Run pipeline on Railway | exec into Railway service; run pipeline with API keys | |

**User's choice:** pg_dump/restore — no API keys needed on Railway during seeding step.

---

## HTTPS / Ingress Layer

**Resolution:** Moot — Railway (backend) and Vercel (frontend) both handle HTTPS automatically. No nginx, Caddy, or ALB needed.

---

## CORS & API Call Routing

| Option | Description | Selected |
|--------|-------------|----------|
| **Via Next.js rewrites** | Vercel proxies server-side to Railway; no browser CORS exposure | ✓ |
| Browser calls Railway directly | CORS middleware in FastAPI; Railway URL exposed to browser | |

**User's choice:** Keep rewrite pattern; no CORS middleware needed.

---

## Railway Postgres pgvector Setup

| Option | Description | Selected |
|--------|-------------|----------|
| **Startup script runs init_db.sql** | `scripts/start.sh`: psql init then uvicorn; idempotent IF NOT EXISTS guards | ✓ |
| Manual setup after provisioning | Run schema manually once; requires manual deploy step | |
| Alembic migration | Full migration framework; overkill for stable schema | |

**User's choice:** Startup script — ensures schema is always present, no manual steps.

---

## Dockerfile for FastAPI

### Ingest pipeline inclusion

| Option | Description | Selected |
|--------|-------------|----------|
| **Include it** | Same image serves API + can run pipeline if needed | ✓ |
| API server only | Separate ingest image; cleaner but extra Dockerfile | |

### Build structure

| Option | Description | Selected |
|--------|-------------|----------|
| **Single-stage python:3.12-slim** | Simple, fast build; sufficient for this corpus size | ✓ |
| Multi-stage build | Smaller final image; overkill for personal tool | |

**User's choice:** Single-stage with ingest pipeline included.

---

## Claude's Discretion

- Article chunking: same greedy paragraph-packing as forum chunker (carried from Phase 6 CONTEXT.md)
- Single `scripts/start.sh` wrapper combining schema init + uvicorn start

## Deferred Ideas

- CI/CD auto-deploy on push to main
- Monitoring / uptime alerting
- Alembic migrations
- Multi-region / CDN caching
