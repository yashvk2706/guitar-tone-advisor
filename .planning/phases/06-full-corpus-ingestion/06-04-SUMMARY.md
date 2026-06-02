---
phase: 06-full-corpus-ingestion
plan: "04"
subsystem: ingestion
tags: [trafilatura, web-scraping, chunker, tdd, loader, article]

# Dependency graph
requires:
  - phase: 06-full-corpus-ingestion/06-01
    provides: RawDocument.metadata field; upsert_chunks source_type param
  - phase: 06-full-corpus-ingestion/06-02
    provides: chunk_pdf() dispatch pattern; _finalize_chunk() helper
  - phase: 06-full-corpus-ingestion/06-03
    provides: chunk_youtube() dispatch pattern; chunk_document() dispatch structure

provides:
  - load_web_articles(urls_file) in app/ingest/loader.py — scrapes URLs via trafilatura
  - chunk_article(raw_doc) in app/ingest/chunker.py — greedy paragraph-packing for articles
  - chunk_document() dispatch route for "web_article" source_type

affects: [06-05-pipeline-wiring, retrieval, generation]

# Tech tracking
tech-stack:
  added: [trafilatura==2.0, lxml_html_clean==0.4.5 (transitive)]
  patterns:
    - Module-level trafilatura imports for patch-point access in tests
    - None-guard before word-count check (T-06-12 Pitfall 6 mitigation)
    - Reuse _finalize_chunk() for article metadata — source_id is URL not filepath
    - chunk_article() is a structural twin of chunk_forum() with no section metadata

key-files:
  created: []
  modified:
    - app/ingest/loader.py
    - app/ingest/chunker.py
    - tests/test_loader.py
    - tests/test_chunker.py

key-decisions:
  - "trafilatura module-level imports (not local) so tests can patch app.ingest.loader.fetch_url and app.ingest.loader.extract"
  - "source_id for web_article = full URL string (e.g. https://...) per CONTEXT.md Claude's Discretion — not a filepath"
  - "chunk_article() reuses _finalize_chunk() verbatim — source_id arg becomes metadata['source_filename'] = URL"
  - "No section_heading or page_number in article chunk metadata — PDF-only keys per D-03"
  - "Token budget test must use single-token marker words (e.g. 'alpha') not compound words; D-02 forbids intra-paragraph splits"

patterns-established:
  - "Pattern: article loader mirrors YouTube loader structure — fetch/extract, None guard, word-count threshold, normalize, hash"
  - "Pattern: article chunker mirrors forum chunker — all identical except metadata source_filename = URL"

requirements-completed: [INGEST-09]

# Metrics
duration: 10min
completed: 2026-06-02
---

# Phase 6 Plan 04: Web Article Loader + Chunker Summary

**trafilatura-backed web article loader with 100-word paywall guard and greedy paragraph chunker storing the full URL in source_filename metadata**

## Performance

- **Duration:** 10 min
- **Started:** 2026-06-02T00:52:12Z
- **Completed:** 2026-06-02T01:02:35Z
- **Tasks:** 2 (each with RED + GREEN TDD commits)
- **Files modified:** 4

## Accomplishments

- `load_web_articles(urls_file)` scrapes 10 Premier Guitar URLs via trafilatura with None-guard before word-count (T-06-12 mitigation)
- `chunk_article()` applies identical greedy paragraph-packing + forward-merge as `chunk_forum()` with URL as `source_filename`
- `chunk_document()` dispatch extended with `elif source_type == "web_article"` routing before `NotImplementedError`
- 10/10 new tests pass (5 loader + 5 chunker), all via mocked trafilatura — zero real network calls in test suite

## Task Commits

Each task was committed atomically with full TDD RED/GREEN cycle:

1. **Task 1 RED: article loader tests** - `827144c` (test)
2. **Task 1 GREEN: load_web_articles()** - `98528eb` (feat)
3. **Task 2 RED: article chunker tests** - `2c5a5e2` (test)
4. **Task 2 GREEN: chunk_article() + dispatch** - `f89c1bc` (feat)

**Plan metadata:** (docs commit below)

_TDD tasks have paired commits (test -> feat)_

## Files Created/Modified

- `app/ingest/loader.py` - Added `from trafilatura import extract, fetch_url` at module level; added `load_web_articles(urls_file)` with None guard and 100-word threshold
- `app/ingest/chunker.py` - Added `elif raw_doc.source_type == "web_article": return chunk_article(raw_doc)` dispatch; added `chunk_article()` function
- `tests/test_loader.py` - 5 new article loader tests with mocked trafilatura (no network I/O)
- `tests/test_chunker.py` - 5 new article chunker tests; fixed token budget test to use single-token marker words

## Decisions Made

- **trafilatura import location:** Module-level (not inside `load_web_articles`) so `unittest.mock.patch("app.ingest.loader.fetch_url")` can intercept it during tests. Local imports would require patching `trafilatura.fetch_url` instead, which is harder to isolate.
- **source_id = URL:** Per CONTEXT.md "Claude's Discretion" — web articles use the full URL string as `source_id` (not a filename/path). This flows through `_finalize_chunk()` unchanged, making `metadata["source_filename"]` carry the URL.
- **chunk_article() as structural twin:** Rather than a `source_type` parameter on `chunk_forum()`, the plan calls for a separate function. This avoids conditional branching in a shared path and keeps each source type's chunker self-contained.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Missing trafilatura package**
- **Found during:** Task 1 GREEN (running tests after implementing load_web_articles)
- **Issue:** `ModuleNotFoundError: No module named 'trafilatura'` — not installed in venv
- **Fix:** `venv/bin/pip install "trafilatura==2.0"` (exact version from CLAUDE.md stack table)
- **Files modified:** venv (not tracked)
- **Verification:** Import succeeds; 5 loader tests pass GREEN
- **Committed in:** `98528eb` (Task 1 GREEN commit)

**2. [Rule 3 - Blocking] Missing lxml_html_clean transitive dependency**
- **Found during:** Task 1 GREEN (trafilatura import failed after install)
- **Issue:** `ImportError: lxml.html.clean module is now a separate project lxml_html_clean` — lxml 6.x split this into a separate package
- **Fix:** `venv/bin/pip install "lxml_html_clean"` (latest compatible version)
- **Files modified:** venv (not tracked)
- **Verification:** trafilatura imports cleanly; all 5 loader tests pass
- **Committed in:** `98528eb` (Task 1 GREEN commit)

**3. [Rule 1 - Bug] Fixed test token budget marker words**
- **Found during:** Task 2 GREEN (test_article_chunks_within_token_budget failed)
- **Issue:** Test used `_paragraph_of_tokens(400, "article{i}word")` — the compound marker `"article0word"` tokenizes as 3 cl100k_base tokens, producing ~1200 tokens per paragraph. D-02 forbids intra-paragraph splits, so the greedy packer emits the oversized paragraph as-is (correct behavior), causing the test to fail incorrectly.
- **Fix:** Changed to single-token markers: `_paragraph_of_tokens(400, "alpha")`, `"beta"`, `"gamma"`, `"delta"` — these produce ~400 tokens each as intended, allowing the greedy packer to split between paragraphs.
- **Files modified:** `tests/test_chunker.py`
- **Verification:** All 5 article chunker tests pass GREEN; 29/29 chunker tests pass
- **Committed in:** `f89c1bc` (Task 2 GREEN commit)

---

**Total deviations:** 3 auto-fixed (2 blocking dependency, 1 bug in test)
**Impact on plan:** All auto-fixes necessary for functionality. No scope creep.

## Issues Encountered

None beyond the auto-fixed deviations above.

## TDD Gate Compliance

- RED gate: `test(06-04)` commits `827144c` (loader) and `2c5a5e2` (chunker) exist before GREEN
- GREEN gate: `feat(06-04)` commits `98528eb` (loader) and `f89c1bc` (chunker) exist after RED
- REFACTOR: No refactoring needed — implementation was clean

## Known Stubs

None — `load_web_articles()` reads real URLs from `raw_data/article_urls.txt`. Network calls are not stubbed in production code (only in tests via mocks).

## Threat Flags

None — threat model T-06-12 (None-dereference) was mitigated by the explicit `if text is None` guard before any `text.split()` call. T-06-09, T-06-10, T-06-11 accepted per plan threat register.

## Next Phase Readiness

- `load_web_articles()` and `chunk_article()` are ready for Plan 06-05 pipeline wiring
- `chunk_document()` dispatch is complete for all 4 source types: forum, pdf_manual, youtube, web_article
- All 4 source type chunkers have passing test coverage (29 chunker + 25 loader tests)

---
*Phase: 06-full-corpus-ingestion*
*Completed: 2026-06-02*
