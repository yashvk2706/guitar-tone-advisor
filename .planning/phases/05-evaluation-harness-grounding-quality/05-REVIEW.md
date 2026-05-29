---
phase: 05-evaluation-harness-grounding-quality
reviewed: 2026-05-29T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - app/eval/retrieval.py
  - app/eval/ragas.py
  - tests/test_eval_retrieval.py
  - tests/test_eval_refusal.py
  - tests/test_eval_ragas.py
findings:
  critical: 2
  warning: 5
  info: 4
  total: 11
findings_resolved:
  critical: 2
  warning: 4
  info: 0
  skipped: 1
  skipped_ids: [WR-05]
status: fixed
fixed_at: 2026-05-29T00:00:00Z
---

# Phase 05: Code Review Report

**Reviewed:** 2026-05-29T00:00:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Reviewed the Phase 5 evaluation harness across two scorer CLIs (`app/eval/retrieval.py`, `app/eval/ragas.py`) and their test suites (`tests/test_eval_retrieval.py`, `tests/test_eval_refusal.py`, `tests/test_eval_ragas.py`). The retrieval scorer is structurally sound with good metric implementations and correct JSONL I/O. The RAGAS faithfulness scorer has two blockers: an event-loop lifetime bug that will cause intermittent failures when scoring more than one tuple, and an unguarded `.content[0]` array access that crashes on any empty API response. The test suites are well-structured for offline coverage but have key gaps around `generate_answer_sync` and cross-run comparison correctness.

---

## Critical Issues

### CR-01: `AsyncAnthropic` client reused across multiple `asyncio.run()` calls — event loop lifetime violation

**File:** `app/eval/ragas.py:393-415`

**Issue:** In `main()`, a single `AsyncAnthropic` instance is created once (line 393) and then passed to `generate_answer_sync()` once per golden tuple in a for loop (lines 408–415). `generate_answer_sync()` calls `asyncio.run()` for each tuple (line 212). Each `asyncio.run()` creates a new event loop, runs to completion, then **closes that loop**. The `AsyncAnthropic` client wraps `httpx.AsyncClient`, which is event-loop-bound. After the first `asyncio.run()` closes its loop, the httpx connection pool is orphaned. On the second call, the client attempts to use a connection pool tied to the now-closed loop, producing `RuntimeError: Event loop is closed` or `httpx.TransportError`. For a single-tuple held-out set (five tuples by default) this will fail on the second tuple.

**Fix:** Create the `AsyncAnthropic` client inside `generate_answer_sync` or inside `_run()` so its lifetime is scoped to the event loop that created it:

```python
# In generate_answer_sync — create a fresh client per call
def generate_answer_sync(
    query: str,
    sources_with_ids: list,
) -> str:
    async def _run() -> str:
        async with AsyncAnthropic() as client:
            parts: list[str] = []
            async for sse in stream_response(
                client=client,
                system_blocks=build_system_blocks(),
                messages=build_messages([], query, sources_with_ids),
                sources_with_ids=sources_with_ids,
                session_id="eval-faithfulness",
            ):
                if sse.event is None:
                    payload = json.loads(sse.data)
                    if "text" in payload:
                        parts.append(payload["text"])
        return "".join(parts)
    return asyncio.run(_run())
```

Remove the `async_client` parameter from both `generate_answer_sync` and `score_tuple_faithfulness`, and remove the `async_client = AsyncAnthropic()` line from `main()`.

---

### CR-02: Unchecked `.content[0]` access on Anthropic API response — `IndexError` on empty response

**File:** `app/eval/ragas.py:271` and `app/eval/ragas.py:293`

**Issue:** Both lines access `resp.content[0].text` without checking that `content` is non-empty. The Anthropic API can return an empty `content` list on a refusal, content-policy block, or transient error (e.g., a `stop_reason` of `"max_tokens"` with no text block, or a safety classifier response). Either access crashes `score_tuple_faithfulness` with `IndexError: list index out of range`, aborting the entire scoring run for all remaining tuples.

```python
# Line 271 — crashes if content is empty
claims = parse_claims(claim_resp.content[0].text)

# Line 293 — crashes if content is empty
if parse_support(support_resp.content[0].text):
```

**Fix:** Guard both accesses with a length check and treat an empty response as parse failure (consistent with the T-05-08 fallback policy):

```python
# Claim extraction (around line 271)
claim_text = claim_resp.content[0].text if claim_resp.content else ""
claims = parse_claims(claim_text)

# Support verification (around line 293)
support_text = support_resp.content[0].text if support_resp.content else ""
if parse_support(support_text):
    supported_count += 1
```

---

## Warnings

### WR-01: `recall@K` labels are incorrect when `--k` is less than 8

**File:** `app/eval/retrieval.py:99-103`

**Issue:** `score_tuple()` always calls `recall_at_k()` with fixed cutoffs of 1, 5, and 8, regardless of the `k` parameter that controls how many chunks `retrieve()` returns. If a user passes `--k 3`, `retrieve()` returns at most 3 results, but the function computes and logs `recall_at_5` and `recall_at_8` against a 3-item list (where `retrieved_ids[:5]` and `retrieved_ids[:8]` both yield all 3 items). The labels in `runs.jsonl` say `"recall_at_5"` and `"recall_at_8"`, but the values actually represent recall@3. Cross-run comparisons using these logged metrics become invalid whenever `--k` is varied.

```python
# Current — fixed cutoffs regardless of k
return {
    "recall_at_1": recall_at_k(t.expected_chunk_ids, retrieved_ids, 1),
    "recall_at_5": recall_at_k(t.expected_chunk_ids, retrieved_ids, 5),  # wrong if k<5
    "recall_at_8": recall_at_k(t.expected_chunk_ids, retrieved_ids, 8),  # wrong if k<8
    "rr": reciprocal_rank(t.expected_chunk_ids, retrieved_ids),
}
```

**Fix:** Clamp the cutoffs to `min(cutoff, k)` so the labels accurately reflect the retrieval depth, or document that `--k` must always be `>= 8` and add an assertion:

```python
def score_tuple(t, k=8, conn=None, embedder=None) -> dict:
    if k < 8:
        raise ValueError(f"k={k} is below the minimum required cutoff of 8")
    results = retrieve(t.query, k=k, conn=conn, embedder=embedder)
    ...
```

Alternatively, compute cutoffs dynamically and rename keys to `f"recall_at_{min(1,k)}"` etc., though a hard assertion is simpler and prevents misleading logs.

---

### WR-02: `format_diff` will `KeyError` if the last run in `runs.jsonl` has different schema keys

**File:** `app/eval/retrieval.py:175`

**Issue:** `format_diff(current, prior)` accesses `prior[key]` for `"recall_at_1"`, `"recall_at_5"`, `"recall_at_8"`, and `"mrr"` with no `KeyError` guard (line 175). `load_last_run()` returns the last line of `runs.jsonl` without any schema validation — it just calls `json.loads()`. If the file is hand-edited, corrupted, or if a different type of record ends up appended (e.g., via a future code path), `format_diff` will crash with `KeyError` and abort the scoring run without writing the new record (since the diff is printed before the append).

```python
# Line 175 — no guard
prev_val = prior[key]   # KeyError if key absent
```

**Fix:** Use `.get()` with a `None` sentinel and handle missing keys gracefully:

```python
def format_diff(current: dict, prior: dict | None) -> str:
    if prior is None:
        ...  # unchanged

    parts = []
    for key, label in [...]:
        prev_val = prior.get(key)
        curr_val = current[key]
        if prev_val is None:
            parts.append(f"{label}: n/a → {curr_val:.2f}")
        else:
            delta = curr_val - prev_val
            arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
            parts.append(f"{label}: {prev_val:.2f} → {curr_val:.2f} ({delta:+.2f} {arrow})")
    return "  ".join(parts)
```

---

### WR-03: `format_diff` compares metrics across different scopes without warning

**File:** `app/eval/retrieval.py:147-181`

**Issue:** `load_last_run()` returns the last run unconditionally, regardless of whether its `scope` matches the current run. If a user alternates between `--held-out` (5 tuples) and `--all` (22 tuples), `format_diff` compares held-out metrics against all-set metrics. The resulting delta has no statistical meaning — a 0.20-point improvement in `recall@1` might simply reflect switching from the harder held-out set to the full set. The scope is stored in the record but never checked before comparison.

**Fix:** In `main()`, filter the prior run by matching scope before passing it to `format_diff`:

```python
prior_raw = load_last_run(args.runs_log)
prior = prior_raw if (prior_raw and prior_raw.get("scope") == scope) else None
if prior_raw and prior is None:
    print(f"  (prior run scope={prior_raw.get('scope')!r} differs — no diff shown)", file=sys.stderr)
print(format_diff(current_record, prior))
```

---

### WR-04: No per-tuple error handling in `ragas.py` main loop — one API failure aborts all remaining tuples

**File:** `app/eval/ragas.py:408-417`

**Issue:** The scoring loop in `main()` calls `score_tuple_faithfulness()` with no exception handling. Any failure (API rate limit, network timeout, `RuntimeError` from the asyncio event loop issue, `IndexError` from CR-02) will propagate through the `try/finally` block, close the DB connection, and terminate the process without writing the partial results to `faithfulness_runs.jsonl`. For a 5-tuple or 22-tuple run with live API calls, losing all results to a single transient error is a significant reliability regression.

**Fix:** Wrap each tuple's scoring in a per-tuple try/except and log failures to stderr while continuing:

```python
for t in sample:
    try:
        result = score_tuple_faithfulness(
            t, k=8, conn=conn, embedder=embedder,
            async_client=async_client, sync_client=sync_client,
        )
    except Exception as e:
        print(f"  ERROR scoring {t.query[:60]!r}: {e!r}", file=sys.stderr)
        result = {
            "query": t.query,
            "faithfulness": None,
            "total_claims": None,
            "supported_claims": None,
            "error": repr(e),
        }
    per_query.append(result)
    ...
```

Then compute `mean_faith` only over non-error results.

---

### WR-05: `_FakeEmbedder` duplicated verbatim across test files

**File:** `tests/test_eval_retrieval.py:53-66`

**Issue:** The `_FakeEmbedder` class at lines 53–66 is marked as a "verbatim copy from `test_retrieval.py` lines 94–112". When the `Embedder` Protocol contract changes (e.g., a new required method, a type signature change, or a new attribute), both copies must be updated independently. This has already happened once (the comment at line 49 acknowledges the copy). A future protocol change will break only the copy that was not updated, causing confusing failures in one test suite but not the other.

**Fix:** Extract `_FakeEmbedder` into a shared conftest fixture:

```python
# tests/conftest.py
import pytest
from app.embeddings.base import EmbeddingResult

class _FakeEmbedder:
    model = "text-embedding-3-small"
    dim = 1536
    provider = "openai"

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 1536

    def embed_documents(self, texts):
        items = list(texts)
        return EmbeddingResult(
            vectors=[[0.0] * 1536] * len(items),
            model=self.model, dim=self.dim, provider=self.provider,
        )

@pytest.fixture
def fake_embedder():
    return _FakeEmbedder()
```

---

## Info

### IN-01: `--held-out` and `--all` flags should use a mutually exclusive group

**File:** `app/eval/retrieval.py:200-212` and `app/eval/ragas.py:341-352`

**Issue:** Both CLIs define `--held-out` (default `True`) and `--all` (sets `held_out=False`) as independent arguments on the same `dest`. Passing both (`--held-out --all`) silently accepts the invocation and applies `--all` (last writer wins). A mutually exclusive group would produce a clear `error: argument --all: not allowed with argument --held-out` message.

**Fix:** Use `add_mutually_exclusive_group()`:

```python
scope_group = p.add_mutually_exclusive_group()
scope_group.add_argument("--held-out", dest="held_out", action="store_true",
                         default=True, help="Score only the 5 held-out tuples (default).")
scope_group.add_argument("--all", dest="held_out", action="store_false",
                         help="Score all 22 tuples.")
```

---

### IN-02: Unnecessary intermediate variable aliases in `score_tuple_faithfulness`

**File:** `app/eval/ragas.py:250-251`

**Issue:** Lines 250–251 unconditionally alias the function parameters to new names with no transformation:

```python
_conn = conn
_embedder = embedder
```

Then `_conn` and `_embedder` are passed directly to `retrieve()` (line 253). These aliases add no clarity and are not used for defensive copying or optional overrides. They create a maintenance hazard where a future reader might expect the aliases to diverge from the parameters.

**Fix:** Remove the aliases and use `conn` and `embedder` directly in the `retrieve()` call.

---

### IN-03: `get_settings()` imported locally in two functions in `ragas.py` instead of at module level

**File:** `app/eval/ragas.py:248` and `app/eval/ragas.py:380`

**Issue:** `get_settings` is imported inside `score_tuple_faithfulness` (line 248) and again inside `main()` (line 380) rather than at the module level. `retrieval.py` imports `get_settings` at module level (line 20). The inconsistency makes `ragas.py` harder to audit for its import surface and slightly increases call overhead (Python re-executes the `import` statement each time, though the module is cached).

**Fix:** Move `get_settings` to the module-level import block alongside the other `app.*` imports.

---

### IN-04: `parse_claims` non-list JSON path (line 117) and `generate_answer_sync` have no test coverage

**File:** `tests/test_eval_ragas.py`

**Issue:** Two code paths in `ragas.py` have no test coverage:

1. `parse_claims()` line 117: `if not isinstance(result, list): return []` — the case where the LLM returns valid JSON that is not an array (e.g., `{"error": "none"}` or `"just a string"`) exercises this branch, but none of the six tests in `test_eval_ragas.py` cover it.

2. `generate_answer_sync()` — the function that bridges async generation into the sync CLI — is entirely untested. There is no test that verifies the async drain, the `asyncio.run()` wrapper, or that `sse.event is None` filtering works correctly.

**Fix:** Add two tests to `test_eval_ragas.py`:

```python
def test_parse_claims_non_list_json():
    from app.eval.ragas import parse_claims
    # Valid JSON but not a list — must return []
    assert parse_claims('{"error": "cannot extract"}') == []
    assert parse_claims('"just a string"') == []

def test_generate_answer_sync_collects_tokens():
    from app.eval.ragas import generate_answer_sync
    from anthropic import AsyncAnthropic
    # Use the _FakeAnthropicClient from test_eval_refusal.py pattern
    # (or import a shared fake)
    # Verify the function returns concatenated token text
    ...
```

---

_Reviewed: 2026-05-29T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
