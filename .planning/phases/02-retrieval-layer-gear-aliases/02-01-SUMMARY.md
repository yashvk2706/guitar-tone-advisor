---
phase: 02-retrieval-layer-gear-aliases
plan: "01"
subsystem: retrieval
tags: [pgvector, regex, lru_cache, psycopg3, gear-aliases, tdd]

# Dependency graph
requires:
  - phase: 01-schema-forum-ingestion-golden-eval
    provides: "app/db.py get_conn() with register_vector, Embedder Protocol, data/forum chunks in pgvector"

provides:
  - "data/gear_aliases.json — 14 corpus-verified bidirectional alias pairs"
  - "app/retrieval/__init__.py — package marker"
  - "app/retrieval/aliases.py — _load_alias_pairs (lru_cache) + expand_query (word-boundary regex)"
  - "app/retrieval/base.py — ChunkResult frozen dataclass + retrieve() function"

affects:
  - "02-02-retrieval-layer (imports retrieve() and ChunkResult)"
  - "02-03-retrieval-tests (full retrieval test suite uses all three files)"
  - "03-generation-chat-ui (calls retrieve() and consumes ChunkResult)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Skip-on-shortform-match in bidirectional alias expansion (avoids Pitfall 3 double-expansion)"
    - "Vector() wrapper for pgvector SELECT params (SELECT <=> needs explicit type; INSERT infers from column)"
    - "lru_cache(maxsize=1) for JSON file loading — same pattern as get_settings()"
    - "alias_pairs=None default in expand_query() — allows test injection without monkeypatching"

key-files:
  created:
    - data/gear_aliases.json
    - app/retrieval/__init__.py
    - app/retrieval/aliases.py
    - app/retrieval/base.py
    - tests/test_retrieval.py
  modified: []

key-decisions:
  - "Skip canonical re.sub when shortform already expanded to avoid double-expansion (Pitfall 3 fix)"
  - "Wrap embed_query output in pgvector.psycopg.Vector() for SELECT <=> params — INSERT works without it because column type provides the cast context; SELECT does not"
  - "Used venv Python (3.12) for test execution — system anaconda Python (3.11) lacks psycopg/pgvector"

patterns-established:
  - "Vector() wrapper pattern: always wrap list[float] in Vector() before passing to <=> in SELECT queries"
  - "expand_query shortform-first with continue: check if shortform fired before applying canonical rule"

requirements-completed:
  - INGEST-07

# Metrics
duration: 6min
completed: 2026-05-19
---

# Phase 2 Plan 01: Gear Alias File + Query Expansion Module Summary

**14 corpus-grounded gear alias pairs in data/gear_aliases.json with bidirectional word-boundary regex expansion in app/retrieval/aliases.py, backed by lru_cache loader and a complete HNSW retrieval function in app/retrieval/base.py**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-19T12:12:50Z
- **Completed:** 2026-05-19T12:19:02Z
- **Tasks:** 2 (Task 2 is TDD: RED commit + GREEN commit)
- **Files created:** 5

## Accomplishments

- Authored `data/gear_aliases.json` with exactly 14 corpus-verified alias pairs (every entry traceable to `raw_data/forum_posts/*.txt` via the Phase 2 grep scan documented in RESEARCH.md)
- Implemented `app/retrieval/aliases.py` with `_load_alias_pairs()` (lru_cache, 3-hop path anchor) and `expand_query()` (word-boundary regex, count=1, IGNORECASE, skip-on-shortform-match to prevent double-expansion)
- Implemented `app/retrieval/base.py` with `ChunkResult` frozen dataclass and `retrieve()` (injectable conn/embedder, Vector() wrapper, no f-string SQL, no openai import, no register_vector call)
- 19/19 tests pass (17 offline unit + 2 live-DB integration); full test suite 96 passed 5 skipped

## Task Commits

1. **Task 1: Author data/gear_aliases.json** — `1a72174` (feat)
2. **Task 2 RED: Failing tests for alias expansion module** — `a3a5a0d` (test)
3. **Task 2 GREEN: Implement app/retrieval package** — `7946086` (feat)

## Files Created/Modified

- `/Users/yashvinaykumar/Desktop/guitar-tone-advisor/data/gear_aliases.json` — 14 corpus-verified alias pairs (Strat/Tele/EVH/SLO/5150/6505/AX8/SD1/GE-7/HM-2/Dual Rec/Maxon 808/SRV/SSS)
- `/Users/yashvinaykumar/Desktop/guitar-tone-advisor/app/retrieval/__init__.py` — empty package marker
- `/Users/yashvinaykumar/Desktop/guitar-tone-advisor/app/retrieval/aliases.py` — _load_alias_pairs (lru_cache) + expand_query (bidirectional word-boundary regex)
- `/Users/yashvinaykumar/Desktop/guitar-tone-advisor/app/retrieval/base.py` — ChunkResult frozen dataclass + retrieve() HNSW function
- `/Users/yashvinaykumar/Desktop/guitar-tone-advisor/tests/test_retrieval.py` — 19 tests covering all Phase 2 Plan 01 behaviors

## Decisions Made

- **Skip-on-shortform-match pattern**: After the shortform `re.sub` fires, skip the canonical `re.sub` for that pair. This prevents "Strat" → "Strat Stratocaster" from then matching "Stratocaster" in the replacement and producing "Strat Strat Stratocaster". The PATTERNS.md pattern ran both subs unconditionally — this deviation was required for correctness.
- **Vector() wrapper for SELECT params**: `pgvector.psycopg.VectorDumper` is only registered for `Vector` and `numpy.ndarray`, NOT for plain `list`. INSERT works without it because the target column type (`vector(1536)`) provides the cast context. A SELECT `<=>` expression has no target type context, so psycopg sends a `list[float]` as `double precision[]` which fails the `vector <=>` operator lookup. Fix: `Vector(embed_query(expanded))`.
- **Test runner**: Used `venv/bin/python -m pytest` throughout — system anaconda Python 3.11 lacks psycopg/pgvector. This was an environment issue, not a code issue.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed double-expansion in expand_query() when shortform fires**
- **Found during:** Task 2 GREEN (test_expand_shortform failure)
- **Issue:** Applying both re.sub rules unconditionally caused "Strat" → "Strat Stratocaster" and then the canonical rule matched "Stratocaster" in the replacement, producing "Strat Strat Stratocaster"
- **Fix:** Added `before = result; result = re.sub(shortform...); if result != before: continue` — skip canonical sub if shortform already expanded
- **Files modified:** `app/retrieval/aliases.py`
- **Verification:** `test_expand_shortform` passes: `"Strat neck pickup clean tone"` → `"Strat Stratocaster neck pickup clean tone"` (not `"Strat Strat Stratocaster..."`)
- **Committed in:** `7946086` (Task 2 GREEN commit)

**2. [Rule 1 - Bug] Wrapped embed_query output in Vector() for pgvector SELECT params**
- **Found during:** Task 2 GREEN (live DB test `test_retrieve_returns_chunk_results` failure)
- **Issue:** `psycopg.errors.UndefinedFunction: operator does not exist: vector <=> double precision[]` — the pgvector VectorDumper is only registered for `Vector` and `numpy.ndarray`, not for `list[float]`. SELECT `<=>` has no column type context to trigger automatic casting.
- **Fix:** Added `from pgvector.psycopg import Vector` import and changed `query_vec = list(embed_query(expanded))` to `query_vec = Vector(embed_query(expanded))`
- **Files modified:** `app/retrieval/base.py`
- **Verification:** All 19 tests pass including `test_retrieve_returns_chunk_results` (live DB)
- **Committed in:** `7946086` (Task 2 GREEN commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — bugs in the plan's specified patterns)
**Impact on plan:** Both fixes were required for correctness. The plan's pattern for expand_query had a double-expansion bug, and the `list(v)` pattern from writer.py INSERT context does not translate to SELECT context. No scope creep.

## Issues Encountered

- **pytest not in venv**: `venv/bin/python -m pytest` failed initially — installed pytest 9.0.3 into the project venv. System anaconda Python lacks project dependencies (psycopg, pgvector). All tests now run correctly with `venv/bin/python`.

## User Setup Required

None — no external service configuration required beyond what Phase 1 already established (DB running via Docker Compose, OPENAI_API_KEY in .env).

## Next Phase Readiness

- `data/gear_aliases.json` + `app/retrieval/aliases.py` are ready for Plan 02 (`retrieve()` calls `expand_query()` before embedding — already wired in `base.py`)
- `app/retrieval/base.py` with `retrieve()` and `ChunkResult` is ready for Plan 02's test suite to exercise directly
- All 3 required files from Plan 01 are committed and verified
- INGEST-07 is satisfied

## Self-Check: PASSED

- data/gear_aliases.json: FOUND
- app/retrieval/__init__.py: FOUND
- app/retrieval/aliases.py: FOUND
- app/retrieval/base.py: FOUND
- tests/test_retrieval.py: FOUND
- 02-01-SUMMARY.md: FOUND
- Commit 1a72174 (feat gear_aliases.json): FOUND
- Commit a3a5a0d (test RED aliases): FOUND
- Commit 7946086 (feat retrieval package GREEN): FOUND

---
*Phase: 02-retrieval-layer-gear-aliases*
*Completed: 2026-05-19*
