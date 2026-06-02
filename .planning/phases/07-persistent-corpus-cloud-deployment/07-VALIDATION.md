---
phase: 7
slug: persistent-corpus-cloud-deployment
status: draft
nyquist_compliant: false
wave_0_complete: true
created: 2026-06-02
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.5.0 |
| **Config file** | `pytest.ini` |
| **Quick run command** | `venv/bin/python -m pytest tests/ -x -q --ignore=tests/test_eval_ragas.py` |
| **Full suite command** | `venv/bin/python -m pytest tests/ -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `venv/bin/python -m pytest tests/ -x -q --ignore=tests/test_eval_ragas.py`
- **After every plan wave:** Run `venv/bin/python -m pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 7-01-01 | 01 | 1 | INGEST-10 | T-06-06 | No shell injection via video_id | static | `venv/bin/python -m pytest tests/test_loader.py -x -q` | ✅ | ⬜ pending |
| 7-01-02 | 01 | 1 | DEPLOY-01 | — | N/A | smoke | `docker build -t guitar-tone-advisor . && echo BUILD_OK` | ❌ Wave 0 (new file) | ⬜ pending |
| 7-01-03 | 01 | 1 | PERSIST-01 | — | N/A | manual | `docker-compose down && docker-compose up -d && docker exec ... psql -c "SELECT COUNT(*) FROM chunks;"` | N/A | ⬜ pending |
| 7-02-01 | 02 | 2 | DEPLOY-05 | — | N/A | static | `grep NEXT_PUBLIC_API_URL frontend/next.config.js` | ✅ | ⬜ pending |
| 7-02-02 | 02 | 2 | DEPLOY-03 | — | Keys not in repo | static | `git grep -rn "sk-ant\|sk-proj" app/ scripts/ Dockerfile 2>/dev/null \|\| echo NO_KEYS_FOUND` | N/A | ⬜ pending |
| 7-03-01 | 03 | 3 | DEPLOY-04 | — | N/A | manual | `psql "$RAILWAY_DATABASE_PUBLIC_URL" -c "SELECT source_type, count(*) FROM chunks GROUP BY source_type;"` | N/A | ⬜ pending |
| 7-04-01 | 04 | 4 | DEPLOY-02 | — | N/A | smoke | `curl -f https://<railway-url>/health` | N/A (post-deploy) | ⬜ pending |
| 7-04-02 | 04 | 4 | DEPLOY-05 | — | N/A | smoke | `curl -f https://<vercel-url>/api/py/health` | N/A (post-deploy) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. No new Python unit test files are needed — Phase 7 adds no new Python logic beyond the yt-dlp fix (which modifies `app/ingest/loader.py`, already covered by `tests/test_loader.py`) and infrastructure files (Dockerfile, start.sh, RUNNING.md, next.config.js).

The yt-dlp fix is the only code change touching tested Python; existing `tests/test_loader.py` covers the loader module.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `pgdata` volume survives `docker-compose down`/`up` | PERSIST-01 | Requires live Docker orchestration; not testable in pytest | Run `docker-compose down && docker-compose up -d`, then `docker exec guitar-tone-advisor-db-1 psql -U postgres -d guitar_tone_advisor -c "SELECT COUNT(*) FROM chunks;"` — count must be unchanged |
| FastAPI app reachable at Railway HTTPS URL | DEPLOY-02 | Requires live Railway deployment | `curl -f https://<railway-url>/health` → `{"status":"ok"}` |
| API keys absent from repo | DEPLOY-03 | Static check + manual repo review | `git grep -rn "sk-ant\|sk-proj\|sk-openai" app/ scripts/ Dockerfile` → no matches |
| Railway Postgres has full corpus | DEPLOY-04 | Requires live Railway Postgres connection | `psql "$RAILWAY_DATABASE_PUBLIC_URL" -c "SELECT source_type, count(*) FROM chunks GROUP BY source_type;"` → ≥656 rows total |
| Vercel frontend proxies to Railway | DEPLOY-05 | Requires live Vercel + Railway deployed | `curl -f https://<vercel-url>/api/py/health` → `{"status":"ok"}` |
| End-to-end tone question from live URL | DEPLOY-05 | Browser UX verification | Open `https://<vercel-url>`, type a tone question, confirm SSE stream with citations appears |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
