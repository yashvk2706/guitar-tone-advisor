---
phase: 02-retrieval-layer-gear-aliases
reviewed: 2026-05-19T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - app/config.py
  - app/retrieval/__init__.py
  - app/retrieval/aliases.py
  - app/retrieval/base.py
  - data/gear_aliases.json
  - tests/test_retrieval.py
findings:
  critical: 1
  warning: 3
  info: 3
  total: 7
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-05-19T00:00:00Z
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Reviewed the Phase 2 retrieval layer: gear alias expansion (`aliases.py`), HNSW dense retrieval (`base.py`), configuration (`config.py`), alias corpus (`gear_aliases.json`), and the test suite (`tests/test_retrieval.py`).

The core retrieval architecture is sound — parameterised SQL, correct Embedder Protocol separation, and the bidirectional expansion design is correct in principle. However, there is a logic bug in `expand_query()` that silently produces wrong (and in one case syntactically corrupted) expanded queries for 6 of the 14 alias pairs in the corpus. This bug exists in production code and is not caught by the test suite because every unit test for `expand_query()` uses the one pair that is unaffected. The remaining findings are defensive-coding gaps and test robustness issues.

---

## Critical Issues

### CR-01: Bidirectional alias expansion silently corrupts queries for 6 of 14 alias pairs

**File:** `app/retrieval/aliases.py:89-108`

**Issue:** The expansion algorithm first tries the shortform regex against the query. For 6 alias pairs, the shortform appears as a whole word *inside* the canonical string. When a user types the canonical form, the shortform regex fires on the shortform token embedded within the canonical — rather than skipping to the canonical rule — producing duplicated or corrupted output:

| User input | Actual result | Expected result |
|---|---|---|
| `"Peavey 5150 amp"` | `"Peavey 5150 Peavey 5150 amp"` | `"5150 Peavey 5150 amp"` |
| `"Peavey 6505 amp"` | `"Peavey 6505 Peavey 6505 amp"` | `"6505 Peavey 6505 amp"` |
| `"Boss GE-7 eq"` | `"Boss GE-7 Boss GE-7 eq"` | `"GE-7 Boss GE-7 eq"` |
| `"Boss HM-2 pedal"` | `"Boss HM-2 Boss HM-2 pedal"` | `"HM-2 Boss HM-2 pedal"` |
| `"Fractal AX8 tone"` | `"Fractal AX8 Fractal AX8 tone"` | `"AX8 Fractal AX8 tone"` |
| `"Soldano SLO-100"` | `"Soldano SLO Soldano SLO-100-100"` | `"SLO Soldano SLO-100"` |

The `SLO` case is the worst: the replacement inserts `SLO Soldano SLO-100` in place of `SLO`, so the trailing `-100` from the original `SLO-100` token is appended to the replacement, yielding `SLO-100-100` — a token that does not exist in the corpus and can only harm retrieval.

No unit test covers any of these 6 pairs; all `expand_query()` tests use `("Strat", "Stratocaster")`, which is not affected because `"Strat"` does not appear as a whole word inside `"Stratocaster"` (it is a prefix, and `\b` correctly prevents the partial match).

**Fix:** Before running the shortform rule, check whether the query already contains the full canonical form. If it does, skip directly to the canonical rule (which correctly prepends the shortform). A minimal fix for the loop body:

```python
for shortform, canonical in pairs:
    replacement = f"{shortform} {canonical}"

    # Guard: if the canonical is already present as a whole word,
    # skip the shortform rule entirely and go straight to canonical expansion.
    # This prevents shortform tokens embedded inside the canonical from firing
    # the wrong rule (e.g. '5150' inside 'Peavey 5150').
    canon_already_present = bool(
        re.search(rf"\b{re.escape(canonical)}\b", result, flags=re.IGNORECASE)
    )
    if not canon_already_present:
        before = result
        result = re.sub(
            rf"\b{re.escape(shortform)}\b",
            replacement,
            result,
            count=1,
            flags=re.IGNORECASE,
        )
        if result != before:
            continue   # shortform fired; canonical now present — done

    # Either canonical was already present, or shortform rule didn't fire.
    # Try to expand canonical → "shortform canonical".
    result = re.sub(
        rf"\b{re.escape(canonical)}\b",
        replacement,
        result,
        count=1,
        flags=re.IGNORECASE,
    )
```

Additionally, add unit tests for at least `("5150", "Peavey 5150")` and `("SLO", "Soldano SLO-100")` covering the canonical-form input case.

---

## Warnings

### WR-01: `_row_to_chunk_result` crashes with `AttributeError` if `metadata_json` is `None`

**File:** `app/retrieval/base.py:98-99`

**Issue:** The helper unconditionally calls `.get()` on `meta`:

```python
meta = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
source_name = meta.get("source_filename", "unknown")
```

When `metadata_json` is `None` (e.g. a `NULL` result from psycopg, a misconfigured row, or a future schema migration that drops the `NOT NULL` constraint), `meta` is `None` and `meta.get(...)` raises `AttributeError`. The schema currently defines `metadata_json JSONB NOT NULL DEFAULT '{}'`, so `NULL` should not arrive today, but this is one schema change away from a silent crash at retrieval time.

**Fix:**
```python
meta = json.loads(metadata_json) if isinstance(metadata_json, str) else (metadata_json or {})
source_name = meta.get("source_filename", "unknown")
```

### WR-02: Live integration tests call the real OpenAI embedder, causing auth failures when `OPENAI_API_KEY` is absent

**File:** `tests/test_retrieval.py:380-402`

**Issue:** `test_retrieve_returns_chunk_results` and `test_alias_retrieval_parity` skip when Postgres is unreachable, but they do **not** inject a fake embedder. When Postgres **is** reachable (e.g. a developer's local machine with Docker running) but `OPENAI_API_KEY` is not in the environment, `retrieve()` calls `get_embedder()` → `OpenAIEmbedder.embed_query()`, which throws an OpenAI authentication error — a confusing failure mode that looks like a test bug rather than a missing env var. The test docstring says nothing about requiring the key.

**Fix:** Either inject `_FakeEmbedder()` (consistent with the offline unit tests), or add a `OPENAI_API_KEY` skip guard:

```python
@pytest.fixture(scope="module")
def db_conn():
    ...
    # add before yield:
    if not get_settings().openai_api_key:
        pytest.skip("OPENAI_API_KEY not set — live embedding tests require it")
    yield conn
    conn.close()
```

Or inject the fake embedder to decouple the live-DB path from the OpenAI path entirely:

```python
def test_retrieve_returns_chunk_results(db_conn):
    results = retrieve("Strat clean tone", k=8, conn=db_conn, embedder=_FakeEmbedder())
```

### WR-03: No unit tests cover the 6 alias pairs where shortform is embedded in canonical

**File:** `tests/test_retrieval.py:140-199`

**Issue:** Every `expand_query()` unit test uses `("Strat", "Stratocaster")` exclusively. This pair is structurally different from the 6 problematic pairs (`5150/Peavey 5150`, `6505/Peavey 6505`, `GE-7/Boss GE-7`, `HM-2/Boss HM-2`, `AX8/Fractal AX8`, `SLO/Soldano SLO-100`) because `"Strat"` is a prefix of `"Stratocaster"` and `\b` prevents the match — but in the 6 broken pairs the shortform is a standalone word inside the canonical. The bug documented in CR-01 is completely invisible to the current test suite.

**Fix:** Add parameterised tests covering canonical-form input for affected pairs:

```python
@pytest.mark.parametrize("query,pair,expected", [
    ("Peavey 5150 amp",   ("5150",  "Peavey 5150"),     "5150 Peavey 5150 amp"),
    ("Boss GE-7 eq",      ("GE-7",  "Boss GE-7"),       "GE-7 Boss GE-7 eq"),
    ("Soldano SLO-100",   ("SLO",   "Soldano SLO-100"), "SLO Soldano SLO-100"),
    ("Fractal AX8 tone",  ("AX8",   "Fractal AX8"),     "AX8 Fractal AX8 tone"),
])
def test_expand_canonical_embedded_shortform(query, pair, expected):
    from app.retrieval.aliases import expand_query
    assert expand_query(query, [pair]) == expected, repr(expand_query(query, [pair]))
```

---

## Info

### IN-01: `_load_alias_pairs` returns a mutable `list` cached by `lru_cache`

**File:** `app/retrieval/aliases.py:32-43`

**Issue:** `lru_cache` caches the return value by reference. If any caller mutates the returned list (e.g. `pairs.append(...)` in a test), the cached value is permanently poisoned for all subsequent calls in the same process. Current code only iterates the list, so there is no active bug, but the `list` type annotation invites mutation.

**Fix:** Return a `tuple` to make the cached value immutable:

```python
return tuple((entry["shortform"], entry["canonical"]) for entry in data["aliases"])
```

Update the return type annotation to `tuple[tuple[str, str], ...]` and `expand_query`'s `alias_pairs` parameter type accordingly.

### IN-02: `database_url` has a default value that contradicts the docstring

**File:** `app/config.py:32`

**Issue:** The docstring on `Settings` says `database_url has no default — every deployment supplies it`, but the field declaration is:

```python
database_url: str = "postgresql://localhost:5432/guitar_tone_advisor"
```

A missing `DATABASE_URL` env var will silently use the default and attempt to connect to a credential-free local database rather than raising a `ValidationError`. This is a documentation/code mismatch that could mask misconfiguration in environments where the default is reachable by coincidence.

**Fix:** Either remove the default to enforce the documented contract:

```python
database_url: str  # no default — must be supplied via DATABASE_URL
```

Or update the docstring to acknowledge the default and its intended scope (local dev only).

### IN-03: `EXPLAIN ANALYZE` in debug mode re-executes the full vector search

**File:** `app/retrieval/base.py:162-170`

**Issue:** When `settings.debug` is `True`, the code runs `EXPLAIN ANALYZE` + `_RETRIEVE_SQL` as a second `cur.execute()` call with the same parameters. `EXPLAIN ANALYZE` actually *executes* the query — it does not merely plan it — so enabling debug mode runs the HNSW scan twice per `retrieve()` call. For a development tool this is low-risk, but it may surprise anyone who assumes the debug path is read-only/free.

**Fix:** Use `EXPLAIN (ANALYZE, FORMAT TEXT, BUFFERS)` if the goal is a plan only, or document the double-execution clearly in a comment. Alternatively, use `EXPLAIN` (without `ANALYZE`) if actual execution statistics are not needed:

```python
cur.execute(
    # NOTE: EXPLAIN (no ANALYZE) — does NOT re-execute the query.
    "EXPLAIN " + _RETRIEVE_SQL,
    (query_vec, embedding_model, query_vec, k),
)
```

---

_Reviewed: 2026-05-19T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
