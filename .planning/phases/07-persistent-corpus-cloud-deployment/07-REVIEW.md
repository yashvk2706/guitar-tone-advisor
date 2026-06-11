---
phase: 07-persistent-corpus-cloud-deployment
reviewed: 2026-06-11T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - Dockerfile
  - scripts/start.sh
  - app/ingest/loader.py
  - app/eval/ragas.py
  - app/generation/prompt.py
  - frontend/next.config.js
  - requirements.txt
  - .gitignore
  - RUNNING.md
findings:
  critical: 3
  warning: 5
  info: 3
  total: 11
status: issues_found
---

# Phase 07: Code Review Report

**Reviewed:** 2026-06-11T00:00:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

This review covers the cloud-deployment phase files: the production Dockerfile and
startup script, the ingestion loader (YouTube/web/PDF), the RAGAS faithfulness CLI,
the generation prompt module, the Next.js proxy config, and project-level config
files. The core generation and retrieval logic is sound. Three blockers were found:
a temp-file credential leak in the cookie-session builder, missing `.dockerignore`
causing 735MB+ of sensitive artifacts (venv, PDFs, node_modules) to be sent to the
Docker daemon on every build, and the `venv/` directory being absent from `.gitignore`
despite showing as untracked (`git status: ?? venv/`). Five warnings cover unhandled
error paths, an unpinned dependency, a misleading variable name, and tracked log files.

---

## Critical Issues

### CR-01: Temp file with Chrome cookies is never deleted

**File:** `app/ingest/loader.py:493-504`
**Issue:** `_build_cookie_session()` creates a `NamedTemporaryFile` with `delete=False`, closes it immediately, writes Chrome cookie data into it via `yt_dlp.YoutubeDL`, loads it into a `MozillaCookieJar`, then returns without ever calling `os.unlink(tmp.name)`. Every call to `load_youtube_transcripts()` leaks one cookie file in the OS temp directory. The file contains the user's authenticated YouTube session cookies extracted from Chrome — a credential artifact that persists until OS reboot or manual cleanup.

**Fix:**
```python
import os

def _build_cookie_session():
    try:
        import http.cookiejar
        import tempfile

        import requests as _requests
        import yt_dlp

        tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        tmp.close()
        try:
            opts: dict = {
                "cookiesfrombrowser": ("chrome",),
                "cookiefile": tmp.name,
                "quiet": True,
            }
            with yt_dlp.YoutubeDL(opts):
                pass
            jar = http.cookiejar.MozillaCookieJar(tmp.name)
            jar.load(ignore_discard=True, ignore_expires=True)
            session = _requests.Session()
            session.cookies = jar  # type: ignore[assignment]
            return session
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    except Exception as exc:
        logger.debug("Cookie session build failed: %r — proceeding without cookies", exc)
        return None
```

---

### CR-02: Missing `.dockerignore` sends 735MB of sensitive artifacts to Docker daemon

**File:** `Dockerfile:1` (root of repository)
**Issue:** No `.dockerignore` file exists. When `docker build` is invoked, the entire repository tree is sent as build context to the Docker daemon before any `COPY` instructions are evaluated. This includes:
- `venv/` — 328MB Python virtualenv (not used in the image)
- `frontend/node_modules/` — 407MB npm tree (not used in the image)
- `raw_data/manuals/*.pdf` — proprietary amp/pedal manuals
- `.git/` — full repository history

None of these are referenced by the Dockerfile `COPY` instructions, so they bloat every build by 735MB+ and expose corpus PDFs and git history to whatever Docker daemon is targeted (including remote Railway builds). A secrets-in-git-history risk also exists if `.env` was ever accidentally committed.

**Fix:** Create a `.dockerignore` file at the repository root:
```
venv/
.venv/
frontend/node_modules/
frontend/.next/
raw_data/
eval/
.git/
.planning/
*.md
.env
.env.*
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
```

---

### CR-03: `venv/` directory is untracked but not gitignored

**File:** `.gitignore`
**Issue:** `git status` shows `?? venv/` — the `venv/` directory (328MB virtualenv, untracked) is not listed in `.gitignore`. The file ignores `.venv/` (with a leading dot) but not `venv/` (without). A `git add .` or IDE auto-stage would accidentally commit the full virtualenv, including copies of all installed packages and potentially `.env`-adjacent files. The `git status` output at the start of this session confirms the directory is currently untracked but not ignored.

**Fix:** Add to `.gitignore`:
```
# Python virtualenv (without leading dot)
venv/
```

---

## Warnings

### WR-01: `get_conn()` outside `try` block in `ragas.main()` — unhandled raise loses clean exit code

**File:** `app/eval/ragas.py:400-401`
**Issue:** `conn = get_conn()` is called on line 400, outside the `try` block that starts on line 401. If `get_conn()` raises (e.g., `DATABASE_URL` is misconfigured or Postgres is unreachable), the `try/finally` block is never entered, `conn` is never bound, and the exception propagates past `sys.exit(main())` as an unhandled exception with a Python traceback. The function signature promises `int` but can raise instead. The caller at `__main__` gets a crash instead of a clean `return 1`.

**Fix:**
```python
def main(argv: list[str] | None = None) -> int:
    ...
    conn = None
    try:
        conn = get_conn()
        settings = get_settings()
        sync_client = Anthropic(api_key=settings.anthropic_api_key)
        ...
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
```

---

### WR-02: `yt-dlp[default]` is unpinned in `requirements.txt`

**File:** `requirements.txt:22`
**Issue:** `yt-dlp[default]` has no version pin. `yt-dlp` releases multiple times per week to keep up with YouTube anti-bot changes; its API surface (CLI flags, Python API, VTT output format) can change without notice. An unpinned install during `docker build` will silently pull the latest version, which may break `--cookies-from-browser chrome`, `--write-auto-subs`, or the subprocess argument list in `_load_via_ytdlp()`. Every other dependency in `requirements.txt` is pinned to a specific version; this one should be too.

**Fix:**
```
yt-dlp[default]==2025.5.22
```
(Pin to the version tested with this code; check `pip show yt-dlp` in the working venv.)

---

### WR-03: `sync_client: Anthropic | None = None` default permits crash-on-call at lines 258 and 283

**File:** `app/eval/ragas.py:227, 258, 283`
**Issue:** `score_tuple_faithfulness` declares `sync_client: Anthropic | None = None` as a keyword argument but calls `sync_client.messages.create(...)` unconditionally on lines 258 and 283 without a `None` guard. If any caller omits `sync_client` (or passes `None` explicitly), both calls raise `AttributeError: 'NoneType' object has no attribute 'messages'`. The `None` default implies the argument is optional, but the function body makes it required.

**Fix:** Either remove the default:
```python
def score_tuple_faithfulness(
    t: GoldenTuple,
    k: int = 8,
    conn=None,
    embedder=None,
    sync_client: Anthropic,   # required — no default
) -> dict:
```
Or add a guard and construct a client if omitted:
```python
if sync_client is None:
    sync_client = Anthropic(api_key=get_settings().anthropic_api_key)
```

---

### WR-04: `CLAIM_SUPPORT_USER` template variable named `chunk_texts` but receives a single chunk's text

**File:** `app/eval/ragas.py:73-76, 292`
**Issue:** The prompt template on line 75 uses `{chunk_texts}` (plural, implying multiple passages). On line 292 it is formatted with `chunk_texts=chunk.text` — a single chunk's text, not a concatenation of multiple chunks. The template says "Source passages:\n{chunk_texts}" (plural "passages"), which will send a single passage while instructing the LLM to reason about "passages". This framing inconsistency may cause the LLM to hedge or reason about absent passages, degrading grounding verdicts. The variable name and prompt text should match the actual single-chunk-per-call semantics.

**Fix:**
```python
CLAIM_SUPPORT_USER = (
    "Claim: {claim}\n\n"
    "Source passage:\n{chunk_text}\n\n"
    "Is this claim supported by the passage above?"
)

# ... and in score_tuple_faithfulness:
content=CLAIM_SUPPORT_USER.format(
    claim=claim,
    chunk_text=chunk.text,
),
```

---

### WR-05: `start.sh` missing `set -u` — unset `DATABASE_URL` silently becomes empty string

**File:** `scripts/start.sh:1-2`
**Issue:** The script uses `set -e` but not `set -u`. If `DATABASE_URL` is unset (e.g., Railway misconfiguration or a missing env var binding), bash expands `"$DATABASE_URL"` to an empty string. `psql ""` with an empty DSN connects to a local Unix socket using the current user's name as the database name, which may succeed (connecting to the wrong DB) or fail with a misleading error that doesn't mention `DATABASE_URL`. With `set -u`, referencing an unset variable immediately aborts with `bash: DATABASE_URL: unbound variable`.

**Fix:**
```bash
#!/usr/bin/env bash
set -euo pipefail

echo "Running schema initialization..."
psql "$DATABASE_URL" -f scripts/init_db.sql

echo "Starting uvicorn on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
```
Note: `${PORT:-8000}` is safe with `-u` because it has an explicit default.

---

## Info

### IN-01: `eval/faithfulness_runs.jsonl` and `eval/runs.jsonl` are tracked in git

**File:** `.gitignore`
**Issue:** `git ls-files eval/` confirms both `eval/faithfulness_runs.jsonl` and `eval/runs.jsonl` are tracked. These are generated runtime artifacts (append-only logs of eval runs). Tracking them causes noisy diffs after every eval run and pollutes git history with operational data rather than source code. They should be gitignored. (`eval/golden_set.jsonl`, `eval/HELD_OUT.md`, and `eval/QUERIES.md` are intentional source artifacts and should remain tracked.)

**Fix:** Add to `.gitignore`:
```
eval/faithfulness_runs.jsonl
eval/runs.jsonl
```

---

### IN-02: `load_pdf_manuals` decorated with `@lru_cache` — stale results on re-ingestion within same process

**File:** `app/ingest/loader.py:143`
**Issue:** `@functools.lru_cache(maxsize=None)` on `load_pdf_manuals` means if the function is called twice with the same `Path` argument within one process, the second call returns the cached first result even if PDF files were added or modified on disk between calls. For the ingestion pipeline (offline CLI, called once), this is harmless. For tests that mock or swap files, or any future use that calls the pipeline multiple times per process, results will silently be stale. The cache buys nothing in the current single-call pipeline but adds hidden state.

**Fix:** Remove the decorator unless a concrete multi-call scenario justifies it. If caching is genuinely needed, document the stale-result contract explicitly.

---

### IN-03: Duplicate `settings = get_settings()` call in `ragas.main()`

**File:** `app/eval/ragas.py:402, 459`
**Issue:** `settings = get_settings()` is called at line 402 (to obtain `anthropic_api_key` for the sync client) and again at line 459 (to obtain `embedding_model` and `anthropic_model` for the run record). Because `get_settings()` is `@lru_cache`'d this is functionally correct, but the second assignment shadows the first binding unnecessarily. The variable from line 402 is still in scope at line 459 and could be reused directly. This is minor but adds confusion when reading the function.

**Fix:** Remove the second call; reuse `settings` from line 402:
```python
# Line 402: settings = get_settings()  # keep
# ...
# Line 459: remove this line — settings is already bound above
record = {
    ...
    "embedding_model": settings.embedding_model,
    "anthropic_model": settings.anthropic_model,
}
```

---

_Reviewed: 2026-06-11T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
