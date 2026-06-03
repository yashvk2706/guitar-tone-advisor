---
phase: 07-persistent-corpus-cloud-deployment
plan: 01
subsystem: infra
tags: [yt-dlp, youtube, ingestion, requirements]

requires:
  - phase: 06-full-corpus-ingestion
    provides: YouTube loader with _load_via_ytdlp() fallback and _VIDEO_ID_RE guard

provides:
  - Fixed _load_via_ytdlp() cmd list using Chrome cookies, no invalid --js-runtimes flag
  - yt-dlp[default] extra in requirements.txt to install yt-dlp-ejs EJS n-challenge solver

affects: [07-persistent-corpus-cloud-deployment]

tech-stack:
  added: [yt-dlp-ejs (via yt-dlp[default] extra)]
  patterns: [Chrome-cookie YouTube auth, no --js-runtimes in yt-dlp subprocess]

key-files:
  created: []
  modified:
    - app/ingest/loader.py
    - requirements.txt

key-decisions:
  - "Added --cookies-from-browser chrome to bypass YouTube IP/bot detection using the operator's authenticated browser session"
  - "Removed --js-runtimes nodejs: 'nodejs' is invalid; yt-dlp accepts node/deno/bun/quickjs; yt-dlp[default] auto-detects via yt-dlp-ejs"
  - "Switched bare yt-dlp to yt-dlp[default] to install yt-dlp-ejs==0.8.0 (EJS n-challenge solver)"

patterns-established:
  - "yt-dlp subprocesses use shell=False and _VIDEO_ID_RE.match(video_id) guard (T-06-06 preserved)"

requirements-completed: [INGEST-10, PERSIST-01]

duration: 5min
completed: 2026-06-02
---

# Phase 7 Plan 01: yt-dlp YouTube Fallback Fix Summary

**Chrome-cookie auth injected into yt-dlp cmd list, invalid `--js-runtimes nodejs` removed, and `yt-dlp[default]` added to install the EJS n-challenge solver**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-02
- **Completed:** 2026-06-02
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `_load_via_ytdlp()` now passes `--cookies-from-browser chrome` to authenticate via the operator's Chrome session, bypassing YouTube's IP/bot blocking
- Removed `--js-runtimes nodejs` (wrong value — yt-dlp accepts `node`/`deno`/`bun`/`quickjs`; auto-detected by yt-dlp-ejs)
- Switched `requirements.txt` from bare `yt-dlp` to `yt-dlp[default]`, installing `yt-dlp-ejs==0.8.0` for EJS n-challenge solving
- All 25 loader tests pass after the edits (`venv/bin/python -m pytest tests/test_loader.py -x -q`)

## Task Commits

1. **Task 1: Fix the yt-dlp fallback cmd list in _load_via_ytdlp()** - `eba61b1` (fix)
2. **Task 2: Switch requirements.txt to yt-dlp[default]** - `dd9194f` (chore)

## Files Created/Modified
- `app/ingest/loader.py` — `_load_via_ytdlp()` cmd list: added `--cookies-from-browser chrome`, removed `--js-runtimes nodejs`
- `requirements.txt` — Changed `yt-dlp` → `yt-dlp[default]`

## Decisions Made
- `--cookies-from-browser chrome` reads cookies from the local Chrome profile at subprocess time; cookies are not logged or persisted beyond subprocess lifetime (T-07-01 accepted per threat model)
- Security mitigations T-06-06 preserved: `_VIDEO_ID_RE.match(video_id)` 11-char allowlist guard and `subprocess.run(shell=False)` — only static flags changed, no untrusted input interpolated

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- yt-dlp fallback is ready for the full pipeline run in Plan 03 (YouTube corpus regeneration step)
- `pip install -r requirements.txt` installs `yt-dlp-ejs` via the `[default]` extra
- Node.js >= 20 must be in PATH at pipeline runtime for the EJS solver (Plan 03 Task 1 documents this)

## Self-Check: PASSED

### Acceptance Criteria Verification

**Task 1:**
- `--cookies-from-browser` present: PASS (grep -c returns 1)
- `"--js-runtimes", "nodejs"` absent: PASS
- `shell=False` preserved: PASS (2 occurrences)
- `_VIDEO_ID_RE.match(video_id)` preserved: PASS
- `venv/bin/python -m pytest tests/test_loader.py -x -q`: PASS (25 passed)

**Task 2:**
- `yt-dlp[default]` line present: PASS
- Bare `yt-dlp` line absent: PASS
- `youtube-transcript-api==1.2.4` and `trafilatura==2.0.0` still present: PASS

---
*Phase: 07-persistent-corpus-cloud-deployment*
*Completed: 2026-06-02*
