# Running Guitar Tone Advisor

## ⚠️ Critical: Volume Persistence Warning

**NEVER run `docker-compose down -v`** — the `-v` flag deletes named Docker volumes,
including `pgdata` which stores all ingested corpus chunks. You would lose the entire
corpus and need to re-run the full ingestion pipeline (OpenAI API costs + time).

**Safe operations:**

| Command | Effect on corpus |
|---------|-----------------|
| `docker-compose down` | Stops containers, **RETAINS** corpus (`pgdata` volume persists) |
| `docker-compose up -d` | Starts containers, uses existing `pgdata` volume |
| `docker-compose restart` | Safe restart, no data loss |
| `docker-compose down -v` | ⛔ DESTROYS `pgdata` — full corpus lost, pipeline re-run required |

**To verify corpus integrity after a restart:**

```bash
docker-compose up -d
docker exec guitar-tone-advisor-db-1 psql -U postgres -d guitar_tone_advisor \
  -c "SELECT source_type, count(*) FROM chunks GROUP BY source_type;"
```

Or using `DATABASE_URL` directly:

```bash
psql "$DATABASE_URL" -c "SELECT source_type, count(*) FROM chunks GROUP BY source_type;"
```

Expected output (after full corpus ingestion):

```
 source_type | count
-------------+-------
 forum       |    21
 pdf_manual  |   ...
 web_article |   ...
 youtube     |   ...
```

---

## Local Development

### Prerequisites

- Docker Desktop running
- Python 3.12 venv at `venv/`
- `.env` file with `DATABASE_URL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`
- Node.js >= 22 for the frontend

### Start the database

```bash
docker-compose up -d
```

### Run the FastAPI backend

```bash
venv/bin/uvicorn app.main:app --reload
```

### Run the Next.js frontend

```bash
cd frontend
npm run dev
```

The app is available at `http://localhost:3000`. The `/api/py/*` rewrite proxies to
`http://localhost:8000` automatically.

### Run the ingestion pipeline

```bash
venv/bin/python -m app.ingest.pipeline \
  --manuals-dir raw_data/manuals \
  --youtube-ids raw_data/youtube_ids.txt \
  --article-urls raw_data/article_urls.txt
```

### Run the test suite

```bash
venv/bin/python -m pytest tests/ -q --ignore=tests/test_eval_ragas.py
```

---

## Cloud Deployment (Railway + Vercel)

See `.planning/phases/07-persistent-corpus-cloud-deployment/07-03-PLAN.md` for the
step-by-step operator deployment workflow (corpus dump, Railway provisioning, Vercel deploy).

### Key env vars (set in Railway dashboard, never committed)

| Variable | Source |
|----------|--------|
| `DATABASE_URL` | Railway internal Postgres URL |
| `OPENAI_API_KEY` | OpenAI dashboard |
| `ANTHROPIC_API_KEY` | Anthropic console |

### Key env vars (set in Vercel dashboard before first build)

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | Railway FastAPI public URL (e.g. `https://guitar-tone-advisor.up.railway.app`) |
