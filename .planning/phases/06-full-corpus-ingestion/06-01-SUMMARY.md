---
phase: "06-full-corpus-ingestion"
plan: "01"
subsystem: ingest
tags: [writer-fix, source-type, raw-document, metadata, tdd]
dependency_graph:
  requires: []
  provides:
    - "upsert_chunks with correct source_type parameter (writer bug fixed)"
    - "RawDocument.metadata field for YouTube segment threading"
  affects:
    - "app/ingest/pipeline.py (call site updated)"
    - "tests/test_writer.py (all call sites updated + 2 new regression tests)"
tech_stack:
  added: []
  patterns:
    - "Required source_type parameter on upsert_chunks — no hardcoded default"
    - "dataclasses.field(default_factory=dict) for mutable default on frozen dataclass"
    - "autouse fixture using request.getfixturevalue to avoid cascading DB skip to static tests"
key_files:
  created: []
  modified:
    - "app/ingest/writer.py"
    - "app/ingest/loader.py"
    - "app/ingest/pipeline.py"
    - "tests/test_writer.py"
decisions:
  - "[06-01] source_type is a required positional parameter on upsert_chunks (not optional with default) — all callers must be explicit about source type; no silent fallback to 'forum'"
  - "[06-01] RawDocument gains metadata: dict[str, Any] = dataclasses.field(default_factory=dict) as the last field — frozen dataclass requires field() for mutable default; YouTube loader stores raw_segments list here"
  - "[06-01] _clean_tables autouse fixture refactored to use request.getfixturevalue instead of direct db_conn parameter — prevents db_conn skip from cascading to static tests"
metrics:
  duration: "~20 minutes"
  completed_date: "2026-05-30"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 4
---

# Phase 6 Plan 01: Fix upsert_chunks Source Type Bug + Extend RawDocument Summary

Fixed the writer bug that would corrupt all Phase 6 chunk rows with `source_type='forum'` regardless of actual source type, then extended `RawDocument` with a `metadata` dict field for threading per-segment YouTube start times into the chunker.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix upsert_chunks signature + extend RawDocument | b2141fc | writer.py, loader.py, pipeline.py, test_writer.py |
| 2 | Add test_upsert_chunks_uses_source_type to test_writer.py | 39f7d4d | tests/test_writer.py |

## What Was Built

**app/ingest/writer.py:**
- Removed `_PHASE_1_SOURCE_TYPE = "forum"` module-level constant
- Added `source_type: str` as sixth required parameter to `upsert_chunks()`
- Updated params tuple to use `source_type` parameter instead of removed constant
- Updated function docstring to document the new parameter and its valid values

**app/ingest/loader.py:**
- Added `import dataclasses` and `from typing import Any` imports
- Added `metadata: dict[str, Any] = dataclasses.field(default_factory=dict)` as last field on `RawDocument`
- Updated docstring: source_type now references correct DB values (`"youtube"` not `"youtube_transcript"`)

**app/ingest/pipeline.py:**
- Updated `upsert_chunks()` call to pass `source_type=raw_doc.source_type` as keyword argument

**tests/test_writer.py:**
- Updated 4 existing `upsert_chunks` call sites (tests 5, 7, 8, 11) to pass `source_type="forum"` explicitly
- Fixed `_clean_tables` autouse fixture to use `request.getfixturevalue("db_conn")` instead of direct parameter, preventing the Postgres-unavailable skip from cascading to static (no-DB) tests
- Added `test_upsert_chunks_source_type_not_hardcoded` (static, no DB): scans writer.py to assert `_PHASE_1_SOURCE_TYPE` is absent
- Added `test_upsert_chunks_uses_source_type` (DB-gated): inserts chunk with `source_type="pdf_manual"` and asserts the stored value is `"pdf_manual"` not `"forum"`

## Verification Results

```
pytest tests/test_writer.py -v
14 items: 2 passed, 12 skipped (DB-gated, Postgres not running in this env)

Static gates passed:
  test_no_fstring_sql_in_writer          PASSED
  test_upsert_chunks_source_type_not_hardcoded  PASSED

Grep gate (count must = 0):
  grep -v '^#' app/ingest/writer.py | grep -c '_PHASE_1_SOURCE_TYPE'  → 0

Signature check:
  def upsert_chunks(conn, document_id, chunks, vectors, embedding_model, source_type: str)

RawDocument metadata field:
  metadata: dict[str, Any] = dataclasses.field(default_factory=dict)  (line 59)

Pipeline call site:
  source_type=raw_doc.source_type  (line 129)

Full suite (excluding test_schema.py which requires live Postgres):
  124 passed, 22 skipped — no regressions
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed _clean_tables autouse fixture cascading skip to static tests**
- **Found during:** Task 1 verification
- **Issue:** `_clean_tables` autouse fixture declared `db_conn` as a direct parameter. When Postgres is unavailable, `db_conn` issues `pytest.skip()`, which cascaded to ALL tests in the module including `test_no_fstring_sql_in_writer` (static, no DB dependency). The plan's done criteria require `test_no_fstring_sql_in_writer` to pass without Postgres.
- **Fix:** Refactored `_clean_tables` to take only `request` as parameter; retrieves `db_conn` via `request.getfixturevalue("db_conn")` only when the test's `fixturenames` includes `"db_conn"`. Static tests are completely isolated from the DB skip.
- **Files modified:** `tests/test_writer.py` (fixture signature only, no assertion logic changed)
- **Commit:** b2141fc

## Known Stubs

None — no stubs or placeholders introduced. Both new functions (`upsert_chunks` with `source_type` and `RawDocument.metadata`) are fully wired.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced. The `source_type` value flows from `raw_doc.source_type` into a DB INSERT; the DB CHECK constraint `source_type IN ('forum','pdf_manual','web_article','youtube')` enforces valid values at the DB level (T-06-01 accepted disposition).

## Self-Check: PASSED

Files confirmed present:
- app/ingest/writer.py — FOUND
- app/ingest/loader.py — FOUND
- app/ingest/pipeline.py — FOUND
- tests/test_writer.py — FOUND

Commits confirmed:
- b2141fc — feat(06-01): fix upsert_chunks source_type bug + extend RawDocument — FOUND
- 39f7d4d — test(06-01): add source_type regression tests to test_writer.py — FOUND
