---
phase: 03-grounded-generation-minimal-chat-ui
reviewed: 2026-05-21T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - app/config.py
  - app/generation/__init__.py
  - app/generation/generator.py
  - app/generation/prompt.py
  - app/main.py
  - app/session.py
  - frontend/app/layout.tsx
  - frontend/app/page.tsx
  - frontend/components/ChatPage.tsx
  - frontend/components/CitationDrawer.tsx
  - frontend/components/CitationPill.tsx
  - frontend/components/CoverageIndicator.tsx
  - frontend/components/MessageBubble.tsx
  - frontend/hooks/useSSEStream.ts
  - frontend/next.config.js
  - tests/test_generation.py
  - tests/test_main.py
  - tests/test_session.py
findings:
  critical: 4
  warning: 5
  info: 3
  total: 12
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-05-21T00:00:00Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

This phase implements the grounded generation module (Anthropic SSE streaming), session store, FastAPI endpoints, and the Next.js chat UI. The architecture follows the spec closely and avoids several documented pitfalls correctly (citation regex post-stream only, no direct openai import, no f-string SQL). However, four blockers were found: a connection leak in every `/chat` request, a synchronous blocking call on the async event loop during retrieval, a prompt-injection risk from unescaped corpus text injected into the XML source block, and a misleading docstring in config.py that contradicts the actual default. Five warnings cover the sliding window oscillation, the hardcoded Anthropic model string, a missing `isStreaming` reset when `onError` fires before `onDone`, a missing `AbortController` for stream cancellation, and an unhandled malformed-SSE path that calls `onError` but continues processing. Three info items cover the `database_url` docstring lie, the unconditional `onDone()` call after `onError()` in the fetch error paths, and the hardcoded `max_tokens=1024` limit.

---

## Critical Issues

### CR-01: Synchronous `retrieve()` Blocks the Async Event Loop on Every `/chat` Request

**File:** `app/main.py:122`

**Issue:** `retrieve()` is a fully synchronous function (declared `def retrieve(...)` in `app/retrieval/base.py:116`). It calls `get_conn()` (a blocking psycopg3 connect), `embed_query()` (a blocking OpenAI HTTP call via the synchronous `openai` client), and a blocking DB query. It is called without `await` or `run_in_executor` inside the `async def chat()` endpoint. This freezes the entire uvicorn event loop for the duration of the embedding + DB round-trip on every request. In practice this means no other requests — including `/health` — can be processed while a `/chat` request is retrieving.

**Fix:** Offload the blocking call to a thread pool:

```python
import asyncio

# In async def chat():
loop = asyncio.get_event_loop()
sources = await loop.run_in_executor(None, retrieve, user_content, 8)
```

Or, longer term, make `retrieve()` fully async using `psycopg`'s async connection API and the async OpenAI client. For now the `run_in_executor` wrapper is the lowest-risk fix.

---

### CR-02: Connection Leak — `retrieve()` Opens a psycopg3 Connection That Is Never Closed

**File:** `app/retrieval/base.py:146` (called from `app/main.py:122`)

**Issue:** When `retrieve()` is called without an injected `conn`, it calls `_conn = get_conn()` which opens a new psycopg3 connection. After the `with _conn.cursor() as cur:` block executes, `_conn` goes out of scope but `_conn.close()` is never called and there is no `with _conn:` context manager. Every `/chat` request therefore leaks one Postgres connection. Under any sustained use, Postgres will exhaust its `max_connections` limit and subsequent connects will fail.

**Fix:** Wrap the connection in a context manager or explicitly close it in a `finally` block:

```python
def retrieve(query, k=8, *, conn=None, embedder=None):
    _conn = conn or get_conn()
    _should_close = conn is None  # only close if we opened it
    try:
        ...
        with _conn.cursor() as cur:
            ...
        return [_row_to_chunk_result(row) for row in rows]
    finally:
        if _should_close:
            _conn.close()
```

---

### CR-03: XML Injection — Unescaped Corpus Text Injected into `<sources>` Block

**File:** `app/generation/prompt.py:107-110`

**Issue:** `build_sources_xml()` interpolates `chunk.source_type`, `chunk.source_name`, and `chunk.text` directly into an XML string with no escaping. A corpus document whose text contains `</source>` (a plausible string in any forum post discussing XML or HTML) will break the XML structure, potentially causing the model to read a different source boundary than intended. A `source_name` or `source_type` containing a double-quote breaks the XML attribute syntax (e.g., `name="foo"bar"` is malformed). Because source content comes from untrusted external data (forum posts, web articles), this is a content-integrity issue that can cause the model to receive silently corrupted source boundaries.

```python
# Current — unsafe for corpus text containing XML special chars:
parts.append(
    f'  <source id="S{i}" type="{chunk.source_type}" name="{chunk.source_name}">'
)
parts.append(f"    {chunk.text}")
```

**Fix:** Use `xml.sax.saxutils.escape` and `quoteattr`:

```python
from xml.sax.saxutils import escape, quoteattr

parts.append(
    f"  <source id=\"S{i}\" type={quoteattr(chunk.source_type)} name={quoteattr(chunk.source_name)}>"
)
parts.append(f"    {escape(chunk.text)}")
```

---

### CR-04: Docstring Lie — `database_url` Claims No Default, But Has One

**File:** `app/config.py:23,34`

**Issue:** The docstring at line 23 states `"database_url has no default — every deployment supplies it."` The actual field declaration at line 34 is:

```python
database_url: str = "postgresql://localhost:5432/guitar_tone_advisor"
```

This is a hardcoded default pointing to a local development database. In any environment where `DATABASE_URL` is not set, the application silently connects to `localhost:5432/guitar_tone_advisor` without warning. If that instance happens to exist and contain stale/wrong data, the application runs against it with no indication anything is wrong. The docstring misleads the operator into believing the app will refuse to start without the variable set — it will not.

**Fix:** Either remove the default so pydantic-settings raises a `ValidationError` if `DATABASE_URL` is absent, or correct the docstring to acknowledge the default exists:

```python
# Option A — remove the default (enforces the "no default" claim):
database_url: str  # required — set DATABASE_URL env var

# Option B — correct the docstring:
# ``database_url`` defaults to ``postgresql://localhost:5432/guitar_tone_advisor``
# for local development. Production deployments must override via DATABASE_URL.
```

---

## Warnings

### WR-01: Sliding Window Drops 2 Turns When Only 1 Excess Exists, Causing Oscillation

**File:** `app/session.py:90-91`

**Issue:** The sliding window check is `if len(turns) > MAX_MESSAGES: del turns[:2]`. This means whenever a single turn pushes `len` to `MAX_MESSAGES + 1`, it immediately deletes two turns, leaving `MAX_MESSAGES - 1` turns. The next append brings it back to `MAX_MESSAGES`, then the next drops it to `MAX_MESSAGES - 1` again. The window oscillates between 19 and 20 messages (with `MAX_MESSAGES=20`). One full turn-pair worth of context is unnecessarily discarded every other message once the window is full.

Concretely: after 21 total appends, `len(turns) == 19` instead of 20. One message was discarded without being at capacity. The test at `tests/test_session.py:66` uses `MAX_MESSAGES + 2` (even) appends, which coincidentally produces the expected `MAX_MESSAGES` length and masks the bug.

**Fix:** Drop only one turn-pair per append, but only when strictly over the limit:

```python
turns.append({"role": role, "content": content})
while len(turns) > MAX_MESSAGES:
    del turns[:2]
```

Or, since we only ever append one at a time, drop exactly 2 only when we're 2 or more over, and drop 1 when we're 1 over — but the cleanest fix matching the intent is to keep the oldest pair deletion but check `>= MAX_MESSAGES + 1` before deleting:

```python
# Simpler: allow up to MAX_MESSAGES+1 then trim to MAX_MESSAGES-1... no.
# The real fix: change the condition to drop just enough:
if len(turns) > MAX_MESSAGES:
    # We added 1, so we're exactly MAX+1. Drop 2 to stay at MAX-1... still oscillates.
    # Correct approach: change the limit so oscillation lands on MAX, not MAX-1:
    #   The check should be: if len(turns) > MAX_MESSAGES + 1: del turns[:2]
    # But that's not right either. The root problem: dropping pairs when len is odd.
    # Best fix: keep the invariant exact by allowing MAX_MESSAGES = even, and only
    # drop when len > MAX_MESSAGES, targeting MAX_MESSAGES - 1 as floor:
    del turns[:2]
# This is the current code. To truly fix: track pairs, not messages.
```

The cleanest fix: accept oscillation is harmless (19 vs 20 messages) or change `MAX_MESSAGES` to be the maximum number of *complete pairs* tracked differently. Minimum acceptable fix: update the docstring to reflect actual behavior (`len(turns)` oscillates between `MAX_MESSAGES-1` and `MAX_MESSAGES`).

---

### WR-02: Hardcoded Anthropic Model String Not Configurable

**File:** `app/generation/generator.py:87`

**Issue:** The model is hardcoded as `"claude-sonnet-4-6"` inside `stream_response()`. There is no `anthropic_model` field in `Settings` (`app/config.py`). Changing the model requires modifying source code. For a personal tool this is low-risk today, but model deprecation will require a code edit rather than an environment variable change. More importantly, tests cannot select a cheaper/faster model via config.

**Fix:** Add a configurable field to `Settings`:

```python
# app/config.py
anthropic_model: str = "claude-sonnet-4-6"
```

And read it in `stream_response()`:

```python
from app.config import get_settings
# ...
async with client.messages.stream(
    model=get_settings().anthropic_model,
    ...
)
```

---

### WR-03: `isStreaming` State Not Reset When `onError` Fires Before `onDone`

**File:** `frontend/components/ChatPage.tsx:123-134`

**Issue:** The `onError` callback at line 123 sets `isStreaming: false` on the assistant message bubble and calls `setIsStreaming(false)` at line 133. However, this only happens in the `onError` callback path. In `useSSEStream.ts`, after calling `onError(...)` in the `catch` block (line 105), the `finally` block calls `onDone()` (line 108). This means `setIsStreaming(false)` is called twice — once in `onError` and once in `onDone`. While React batches state updates so double-setting is harmless, the concern is the converse: if `onError` is called mid-stream by the malformed JSON path (line 84 of `useSSEStream.ts`), `onError` is called but streaming continues — the loop does `continue` instead of `return`. In that case, `setIsStreaming(false)` fires prematurely while the stream is still active, re-enabling the input textarea while the model is still streaming.

**Fix:** In `useSSEStream.ts`, when `onError` is called for malformed JSON (line 84), either `break` out of the loop or not call `onError` for per-event parse failures (downgrade to a no-op skip):

```typescript
// Option A: skip malformed events silently instead of calling onError
// (malformed JSON is a transient parse error, not a fatal stream error)
try {
  parsed = JSON.parse(dataLine) as Record<string, unknown>;
} catch {
  continue; // skip malformed event, do not call onError
}

// Option B: if calling onError for malformed JSON is intentional, break:
try {
  parsed = JSON.parse(dataLine) as Record<string, unknown>;
} catch {
  onError(new Error(`Malformed SSE data: ${dataLine}`));
  break; // stop processing; finally will call onDone
}
```

---

### WR-04: No `AbortController` — Stream Cannot Be Cancelled

**File:** `frontend/hooks/useSSEStream.ts:29`

**Issue:** `streamChat()` uses `fetch()` with no `AbortController`. If the user clicks "New Chat" (`handleNewChat` in `ChatPage.tsx:162`) while a stream is in progress, the React state resets but the underlying fetch/ReadableStream continues reading in the background. The orphaned stream's callbacks fire on stale closure references, calling `setMessages` on state that no longer exists in the component. React will log a state-update-after-unmount warning, and `setSessionId` could corrupt the new chat's session if the server sends a `session` event after reset.

**Fix:** Accept an `AbortSignal` in `streamChat()` and thread it through `fetch`:

```typescript
export async function streamChat(
  message: string,
  sessionId: string | null,
  gear: object | null,
  onSession: SessionCallback,
  onToken: TokenCallback,
  onCitations: CitationsCallback,
  onError: ErrorCallback,
  onDone: () => void,
  signal?: AbortSignal,  // add this
): Promise<void> {
  // ...
  response = await fetch('/api/py/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message, gear }),
    signal,  // pass through
  });
```

In `ChatPage.tsx`, hold an `AbortController` ref and abort it in `handleNewChat` and `useEffect` cleanup.

---

### WR-05: Unescaped User Message Content in XML `<gear>` Block

**File:** `app/main.py:117`

**Issue:** The gear dict value is injected as JSON inside an XML-like `<gear>` tag using an f-string: `f"<gear>{json.dumps(req.gear)}</gear>\n\n{req.message}"`. While `json.dumps` serializes the dict safely, `req.message` (the raw user text) is concatenated unmodified immediately after the closing `</gear>` tag. A user typing `</gear><system>` in their message cannot close the XML tags (since the `<gear>` content is a dict, not free text), but the `req.message` itself is never validated for length. An arbitrarily long message is inserted into the context window, with no size cap enforced before the Anthropic API call. There is no message length validation in `ChatRequest` or in the endpoint before `retrieve()` and `build_messages()` are called.

**Fix:** Add a `max_length` validator on `ChatRequest.message`:

```python
from pydantic import field_validator

class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    gear: dict | None = None

    @field_validator("message")
    @classmethod
    def message_not_empty_or_too_long(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be empty")
        if len(v) > 4000:
            raise ValueError("message too long (max 4000 chars)")
        return v
```

---

## Info

### IN-01: `onDone()` Called Unconditionally After `onError()` in Fetch Error Paths

**File:** `frontend/hooks/useSSEStream.ts:35-37, 41-43`

**Issue:** Both early-exit error paths (network error and non-2xx response) call `onError(...)` followed immediately by `onDone()`. This means `ChatPage.tsx`'s `onDone` handler always fires, which calls `setIsStreaming(false)` even though `onError` already did so. This is harmless because React batches updates, but it creates an implicit contract that `onDone` always fires even after an error — if callers ever try to use `onDone` as "success-only" signal, they will be surprised.

**Fix:** Document explicitly in the `streamChat` signature that `onDone` is always called on completion regardless of error, or separate "done-on-success" from "done-always" semantics.

---

### IN-02: `app/generation/__init__.py` Is Empty

**File:** `app/generation/__init__.py`

**Issue:** The file is completely empty (zero bytes). While Python allows empty `__init__.py`, the rest of the `app/` package modules have module-level docstrings. An empty `__init__.py` is fine functionally but inconsistent with project convention.

**Fix:** Add a one-line module docstring matching the pattern used elsewhere:

```python
"""Grounded response generation — Anthropic streaming + citation validation."""
```

---

### IN-03: Hardcoded `max_tokens=1024` in `stream_response()`

**File:** `app/generation/generator.py:88`

**Issue:** `max_tokens=1024` is a magic number hardcoded in the Anthropic API call. For complex multi-pedal signal chain recommendations with multiple cited sources, 1024 tokens can be insufficient, causing the model to truncate mid-recommendation. This is not configurable without a code change.

**Fix:** Add `anthropic_max_tokens: int = 1024` to `Settings` in `app/config.py`, and read it in `stream_response()`:

```python
max_tokens=get_settings().anthropic_max_tokens,
```

---

_Reviewed: 2026-05-21T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
