# Phase 3: Grounded Generation & Minimal Chat UI — Research

**Researched:** 2026-05-19
**Domain:** Anthropic SDK streaming, FastAPI SSE, in-process session memory, Next.js App Router chat UI
**Confidence:** HIGH (all stack claims verified against installed packages; UI patterns verified against sse-starlette and anthropic SDK source code in the active venv)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** App Router + TypeScript + Tailwind CSS only. No CSS Modules for Phase 3.
- **D-02:** Next.js app lives in `frontend/` directory. Dev command: `cd frontend && npm run dev`. `frontend/next.config.js` configures `/api/py/*` → `localhost:8000` rewrites.
- **D-03:** Model: `claude-sonnet-4-6`, temperature 0.1.
- **D-04:** Prompt caching via `cache_control: {"type": "ephemeral"}` on system prompt TextBlockParam.
- **D-05:** Fetch + ReadableStream SSE in Next.js — no EventSource, no Vercel AI SDK.
- **D-06:** SSE event sequence: (1) `event: session` → (2) plain `data:` token chunks → (3) `event: citations`.
- **D-07:** `session_id` sent in request body (`null` on first turn, UUID thereafter). Persisted in React `useState`.
- **D-08:** Post-stream citation validation — stream tokens live, accumulate full response, extract `[Sn]` regex after stream completes, emit only valid source IDs in `event: citations`.
- **D-09:** Citation regex: `r'\[S(\d+)\]'` — collect unique ints, discard where `n > len(sources)`.
- **D-10:** In-process Python dict keyed by `session_id` (UUID). No Redis, no DB storage.
- **D-11:** Gear lives in first user message as `<gear>` block. System prompt stays stable for prompt caching.
- **D-12:** Sliding window: retain last 10–15 turn pairs (20–30 messages). Drop oldest pair on overflow. No summarization.
- **D-13:** System prompt must enforce three hard rules: (1) cite every concrete recommendation with `[Sn]`, (2) refuse with reason when corpus lacks material, (3) never cite a source not in `<sources>`.
- **D-14:** `<sources>` XML block format with `id="S1"`, `type=`, `name=` attributes and chunk text.
- **D-15:** `POST /chat` request body: `{"session_id": "uuid-or-null", "message": "...", "gear": {...}}`.
- **D-16:** `GET /sources/{chunk_id}` returns full chunk text + parent document metadata.
- **D-17:** `DELETE /sessions/{session_id}` deferred — "New chat" generates a fresh UUID client-side.

### Claude's Discretion

- Module placement: `app/generation/__init__.py` (empty), `app/generation/prompt.py`, `app/generation/generator.py`.
- Exact `sse-starlette` event format — defer to 3.4.4 docs (now verified: see Code Examples).
- `frontend/` directory structure: `app/` (App Router), `components/`, `hooks/`.
- Coverage indicator wording (e.g., "3 sources agree").

### Deferred Ideas (OUT OF SCOPE)

- `DELETE /sessions/{session_id}` endpoint.
- CSS Modules (deferred to Phase 4).
- `neighbor_chunks` in `/sources/{chunk_id}` response.
- Upgrade to `claude-opus-4-7`.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GEN-01 | Claude generates tone recommendations drawing only from retrieved passages | System prompt grounding rules (D-13) + `<sources>` XML injection (D-14) |
| GEN-02 | Responses include inline `[S1]`, `[S2]` citations attached to specific claims | Citation regex D-09 + prompt enforcement D-13 |
| GEN-03 | Responses include concrete knob positions 0–10 when corpus supports it | System prompt format directive + corpus already has exact numbers |
| GEN-04 | Responses include signal chain order when relevant | System prompt format directive |
| GEN-05 | Gear translation when user gear differs from corpus gear | System prompt explicit gear-translation instruction |
| GEN-06 | Refusal with reason when corpus lacks sufficient material | System prompt hard rule #2 (D-13) + empty-chunk detection in generator |
| GEN-07 | Responses stream token-by-token via SSE; citations sent as out-of-band payload after stream | sse-starlette EventSourceResponse + anthropic AsyncMessageStream.text_stream |
| CHAT-01 | User types gear + tone in natural language, receives grounded recommendation | End-to-end flow: frontend POST → FastAPI → retrieve() → generate() → SSE |
| CHAT-02 | Per-session conversation history maintained (in-process; cleared on restart or new chat) | `app/session.py` in-process dict (D-10) |
| CHAT-03 | "New chat" button clears session | React state reset + fresh `session_id=null` on next POST |
| CITE-01 | Each `[Sn]` citation is clickable, opens drawer showing raw chunk text and source name | Citation pills rendered from `event: citations` payload; lazy fetch via `GET /sources/{chunk_id}` |
| CITE-02 | Each citation displays source-type label: `[Forum]`, `[Manual]`, `[Article]`, `[YouTube]` | `source_type` field in `event: citations` payload maps to label in citation drawer |
| CITE-03 | Each answer displays corpus coverage indicator ("N sources agree") | `len(validated_citations)` from post-stream regex pass |
</phase_requirements>

---

## Summary

Phase 3 wires the full end-to-end slice: Anthropic SDK streaming → FastAPI SSE endpoint → in-process session memory → minimal Next.js chat UI. The retrieval layer (`app/retrieval/base.retrieve()` returning `list[ChunkResult]`) and the embedder protocol are complete from Phase 2. Phase 3 adds the generation module, the HTTP serving layer, and the frontend.

The three technically novel elements in this phase are: (1) the async streaming pattern with `AsyncMessageStream.text_stream` plus SSE named events via `sse-starlette`'s `ServerSentEvent` dict-yield format, (2) the post-stream citation extraction and validation step that must accumulate the full response before emitting `event: citations`, and (3) the frontend's custom ReadableStream SSE parser (no EventSource because `/chat` is POST). All three have been verified against the installed packages.

The UI contract is already approved in `03-UI-SPEC.md`. No design decisions remain open for Phase 3. The planner should treat `03-UI-SPEC.md` as authoritative on all visual and interaction details.

**Primary recommendation:** Build in this order — generation module (Plan 1), then FastAPI endpoint (Plan 2), then session memory (Plan 3), then frontend (Plan 4). Each plan produces a testable artifact; the order matches the data flow direction.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Prompt construction (`<sources>` XML, system prompt) | API / Backend (`app/generation/prompt.py`) | — | LLM prompt must be server-side; client never sees raw chunks |
| Streaming token generation | API / Backend (`app/generation/generator.py`) | — | Anthropic SDK calls happen server-side |
| SSE event emission | API / Backend (`app/main.py` via sse-starlette) | — | FastAPI streams SSE; Next.js consumes it |
| Citation validation (regex + range check) | API / Backend (`app/generation/generator.py`) | — | Requires access to `list[ChunkResult]`; must be server-side |
| Session memory (conversation history) | API / Backend (`app/session.py`) | — | In-process dict; single-user local; acceptable to lose on restart |
| Chunk text retrieval for drawer | Database / Storage (`chunks` table via `GET /sources/{chunk_id}`) | — | Lazy fetch on citation click; text lives in Postgres |
| SSE parsing and token rendering | Browser / Client (Next.js `useSSEStream` hook) | — | ReadableStream consumer; TextDecoder splits `\n\n` frames |
| Citation pill + drawer UI | Browser / Client (Next.js components) | — | React state manages pill reveal and drawer open/close |
| Session ID lifecycle | Browser / Client (React `useState`) | API / Backend (UUID generation on first turn) | Client stores and forwards UUID; server creates on `session_id=null` |
| Next.js `/api/py/*` → `localhost:8000` proxy | Frontend Server (Next.js dev rewrite) | — | Rewrites in `next.config.js`; no CORS config needed |

---

## Standard Stack

### Core (all already in requirements.txt — no new installs needed for Python)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `anthropic` | 0.102.0 | LLM streaming via `AsyncAnthropic.messages.stream()` | Project decision; SDK verified installed in venv |
| `sse-starlette` | 3.4.4 | `EventSourceResponse` wrapping async generator | Project decision; verified installed |
| `fastapi` | 0.136.1 | `POST /chat`, `GET /sources/{chunk_id}`, `GET /health` | Project decision; verified installed |
| `uvicorn` | 0.46.0 | ASGI server for FastAPI | Already in requirements.txt |
| `psycopg[binary]` | 3.3.4 | `GET /sources/{chunk_id}` → `chunks` table lookup | Already used in retrieval layer |
| `pydantic-settings` | 2.14.1 | `anthropic_api_key` field on Settings | Already used; just needs new field |

[VERIFIED: npm registry] Next.js ecosystem (new installs for `frontend/`):

| Package | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `next` | 15.x (latest stable: 15.x series recommended) | App Router, TypeScript, rewrites | D-01 locks App Router |
| `typescript` | 5.x | Type safety | Next.js default |
| `tailwindcss` | 4.3.0 (latest) | Styling — no component library (D-01) | Confirmed latest via npm view |
| `lucide-react` | 1.16.0 (latest) | Icons: ArrowUp, X, SquarePen, Guitar | Approved in UI-SPEC, MIT license |

> Note on Next.js version: `npm view next version` returns 16.2.6 as of research date. However, this is a pre-release version. The stable production version is the 15.x line. Run `npx create-next-app@latest` to get the version create-next-app recommends. The planner should not hardcode `next@16.x` in `package.json` — use `create-next-app` defaults and verify the installed version.

[ASSUMED] The `create-next-app` scaffolded version for the stable release. Use `create-next-app` rather than manually specifying a Next.js version.

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `uuid` (Python stdlib) | stdlib `uuid` module | Server-side UUID generation for new sessions | First-turn `session_id=null` → server calls `str(uuid.uuid4())` |
| `re` (Python stdlib) | stdlib | Citation regex `r'\[S(\d+)\]'` | Post-stream validation in `generator.py` |
| `json` (Python stdlib) | stdlib | SSE event payload serialization | `json.dumps()` for all SSE event `data:` fields |

### Not Needed (explicitly excluded)

| Excluded | Reason |
|----------|--------|
| Vercel AI SDK | D-05 — project constraint (same category as LangChain) |
| EventSource browser API | D-05 — GET-only, `/chat` is POST |
| LangChain / LlamaIndex | CLAUDE.md hard constraint |
| `psycopg_pool` | Not installed; Phase 3 uses single connection per request in `GET /sources/{chunk_id}` and the retrieval path already uses `get_conn()` |
| `pytest-asyncio` | Not installed — use `starlette.testclient.TestClient` (sync) for FastAPI route tests |

**Installation (frontend only — Python deps already installed):**
```bash
cd frontend
npx create-next-app@latest . --typescript --tailwind --app --no-src-dir --import-alias "@/*"
npm install lucide-react
```

---

## Architecture Patterns

### System Architecture Diagram

```
User Input (browser)
       │
       │  POST /api/py/chat  (Next.js rewrite → localhost:8000/chat)
       ▼
┌──────────────────────────────────────────────────┐
│  FastAPI POST /chat                              │
│                                                  │
│  1. Parse request body (session_id, message,     │
│     optional gear)                               │
│  2. Load or create session (app/session.py)      │
│  3. Append user message to history              │
│  4. Call retrieve(message, k=8) → list[ChunkResult]│
│  5. Build messages list (prompt.py):             │
│     - system: [TextBlockParam + cache_control]   │
│     - history: prior turns from session          │
│     - final user msg: <sources>XML + user text   │
│  6. Yield event: session → UUID                  │
│  7. AsyncMessageStream.text_stream → yield tokens│
│  8. Accumulate full_response text               │
│  9. Post-stream citation regex → validate        │
│  10. Yield event: citations → valid chunk_ids    │
│  11. Append assistant response to session history│
└──────────────────────────────────────────────────┘
       │
       │  SSE stream (text/event-stream)
       ▼
┌──────────────────────────────────────────────────┐
│  Next.js useSSEStream hook                       │
│                                                  │
│  ReadableStream.getReader() loop:                │
│  TextDecoder → buffer → split \n\n               │
│                                                  │
│  event: session  → setSessionId(uuid)            │
│  data: {"text":…} → append to assistant bubble  │
│  [done]          → remove ▋ cursor               │
│  event: citations → render pills + indicator     │
└──────────────────────────────────────────────────┘
       │
       │  Click citation pill → GET /api/py/sources/{chunk_id}
       ▼
┌──────────────────────────────────────────────────┐
│  FastAPI GET /sources/{chunk_id}                 │
│  → chunks JOIN documents query                   │
│  → {text, source_type, source_name, ...}         │
└──────────────────────────────────────────────────┘
       │
       ▼
  Citation Drawer (React state → render chunk text)
```

### Recommended Project Structure

```
app/
├── generation/
│   ├── __init__.py           # empty (mirrors retrieval/ pattern)
│   ├── prompt.py             # build_system_prompt(), build_messages()
│   └── generator.py          # stream_response() async generator
├── session.py                # SessionStore: dict[str, list[dict]], sliding window
└── main.py                   # FastAPI app, POST /chat, GET /sources/{chunk_id}, GET /health

frontend/
├── app/
│   ├── layout.tsx            # root layout: font, bg-zinc-950
│   └── page.tsx              # chat page (client component)
├── components/
│   ├── ChatPage.tsx          # top-level: header, MessageList, InputBar
│   ├── MessageBubble.tsx     # user + assistant bubble variants
│   ├── CitationPill.tsx      # [Sn] pill — blue, clickable
│   ├── CitationDrawer.tsx    # right-side overlay: source type badge + chunk text
│   └── CoverageIndicator.tsx # "● N sources agree"
├── hooks/
│   └── useSSEStream.ts       # ReadableStream SSE parser → callbacks
└── next.config.js            # rewrites: /api/py/* → localhost:8000/*
```

### Pattern 1: Anthropic SDK Async Streaming with Named SSE Events

**What:** Use `AsyncAnthropic` (not sync `Anthropic`) inside an async FastAPI route. The async context manager `async with client.messages.stream(...)` yields an `AsyncMessageStream`. Iterate `stream.text_stream` for token deltas. After the stream exits the context manager, call `stream.get_final_message()` to get the accumulated response.

**When to use:** Any SSE route that proxies Anthropic streaming output.

```python
# Source: anthropic 0.102.0 SDK source — verified in venv
# app/generation/generator.py

import json
import re
import uuid
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from sse_starlette.event import ServerSentEvent

from app.retrieval.base import ChunkResult

_CITATION_RE = re.compile(r'\[S(\d+)\]')


async def stream_response(
    *,
    client: AsyncAnthropic,
    system_blocks: list[dict],      # list of TextBlockParam dicts
    messages: list[dict],           # anthropic MessageParam list
    sources: list[ChunkResult],     # the retrieved chunks for this turn
    session_id: str,
) -> AsyncIterator[ServerSentEvent]:
    """Yield SSE events: session → token data → citations."""

    # 1. Session event (always first, even on follow-up turns)
    yield ServerSentEvent(
        data=json.dumps({"session_id": session_id}),
        event="session",
    )

    full_response = []

    # 2. Stream tokens
    async with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system_blocks,          # list of TextBlockParam with cache_control
        messages=messages,
        temperature=0.1,
    ) as stream:
        async for text in stream.text_stream:
            full_response.append(text)
            yield ServerSentEvent(data=json.dumps({"text": text}))

    # 3. Post-stream citation validation
    response_text = "".join(full_response)
    raw_ns = set(int(n) for n in _CITATION_RE.findall(response_text))
    valid_ns = {n for n in raw_ns if 1 <= n <= len(sources)}

    citations_payload = [
        {
            "id": f"S{n}",
            "chunk_id": sources[n - 1].chunk_id,
            "source_type": sources[n - 1].source_type,
            "source_name": sources[n - 1].source_name,
        }
        for n in sorted(valid_ns)
    ]

    yield ServerSentEvent(
        data=json.dumps({"sources": citations_payload}),
        event="citations",
    )
```

Key facts verified in the SDK source code:
- `AsyncMessageStream.text_stream` is an `AsyncIterator[str]` yielding text deltas only (it filters out thinking, tool_use, etc.)
- The `async with client.messages.stream(...)` pattern is the `AsyncMessageStreamManager` context manager — `__aenter__` returns the `AsyncMessageStream` directly
- `stream.get_final_message()` is available after the `async with` block exits if needed
- `system` parameter accepts `Union[str, Iterable[TextBlockParam]]` — pass a list of dicts with `{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}`

### Pattern 2: FastAPI SSE Route with EventSourceResponse

**What:** Return `EventSourceResponse` from a `POST` route. Pass an async generator that yields `ServerSentEvent` objects (or dicts that `ensure_bytes()` converts to `ServerSentEvent` automatically). For named events, use `ServerSentEvent(data=..., event="session")`.

**When to use:** `POST /chat` — must be POST because the request body carries `session_id` and `message`.

```python
# Source: sse-starlette 3.4.4 SDK source — verified in venv
# app/main.py

import json
import uuid

from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse
from sse_starlette.event import ServerSentEvent
from pydantic import BaseModel

from app.generation.generator import stream_response
from app.session import get_or_create_session, append_turn

app = FastAPI()


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    gear: dict | None = None   # only on first turn


@app.post("/chat")
async def chat(req: ChatRequest):
    # Resolve session
    sid = req.session_id or str(uuid.uuid4())
    session = get_or_create_session(sid)

    # If first turn with gear, inject <gear> block into user message
    user_content = req.message
    if req.gear and not session["turns"]:   # first turn
        user_content = f"<gear>{json.dumps(req.gear)}</gear>\n\n{req.message}"

    # Retrieve relevant chunks
    from app.retrieval.base import retrieve
    sources = retrieve(user_content, k=8)

    # Build anthropic messages (history + new user message with <sources>)
    from app.generation.prompt import build_messages, build_system_blocks
    messages = build_messages(session["turns"], user_content, sources)
    system_blocks = build_system_blocks()

    # Append user turn to session history BEFORE streaming
    # (assistant turn appended after streaming completes — do in background or
    # track full_response in an accumulator inside the generator wrapper)

    async def event_gen():
        async for sse_event in stream_response(
            client=_get_anthropic_client(),
            system_blocks=system_blocks,
            messages=messages,
            sources=sources,
            session_id=sid,
        ):
            yield sse_event

    return EventSourceResponse(event_gen())
```

Verified SSE wire format from `ServerSentEvent.encode()`:
```
# event: session → data payload
event: session\r\n
data: {"session_id": "abc-123"}\r\n
\r\n

# plain data token
data: {"text": " warm"}\r\n
\r\n

# event: citations → sources list
event: citations\r\n
data: {"sources": [{"id": "S1", "chunk_id": "...", "source_type": "forum", "source_name": "bb_king_tone.txt"}]}\r\n
\r\n
```

**Critical:** `EventSourceResponse` constructor accepts `content: AsyncIterable[ServerSentEvent | dict | str | bytes]`. Yielding `ServerSentEvent` objects is the clearest pattern. Yielding dicts also works — `ensure_bytes()` converts `{"data": "...", "event": "session"}` to `ServerSentEvent(**dict)`.

### Pattern 3: Prompt Caching on System Prompt

**What:** Wrap the system prompt text in a `list[TextBlockParam]` and add `cache_control: {"type": "ephemeral"}` to the final block. This enables Anthropic's prompt caching for follow-up turns in a session, reducing TTFT.

**When to use:** System prompt must remain stable across turns (D-11 ensures this by keeping gear in the first user message, not the system prompt).

```python
# Source: anthropic 0.102.0 types — verified in venv
# app/generation/prompt.py

SYSTEM_PROMPT_TEXT = """You are a guitar tone advisor. You help a guitarist achieve specific sounds
by giving concrete, actionable recommendations: amp channel selection, EQ settings
(bass/mid/treble values 0–10), gain/drive levels, pedal selection and order,
guitar pickup selection, and playing technique notes.

GROUNDING RULES (non-negotiable):
1. Every concrete recommendation (specific gear, specific setting, specific technique)
   must be supported by at least one passage from <sources>. Cite it inline as [Sn]
   where n is the source number.
2. When the corpus lacks material for a query, refuse plainly:
   "I don't have material on [X] — the closest I have is [Y], want that instead?"
   Do NOT fabricate recommendations.
3. Never cite a source not in the <sources> block. n in [Sn] must be 1 ≤ n ≤ N
   where N is the total number of sources provided.
4. When sources conflict, surface the disagreement: "Source [S1] suggests X,
   [S3] suggests Y — the difference is..."
5. The user's gear context is in the first user message in a <gear> block.
   Trust it for the whole conversation. Do not ask for gear again.

FORMAT:
- Lead with a 1-2 sentence "what you're going for" summary.
- Bulleted signal-chain recommendation: guitar → pedals (in order) → amp.
- Specific EQ settings as a compact list (e.g., Bass=7 Mid=4 Treble=6).
- Inline citations throughout — e.g., "Set gain around 4 [S2]".
- End with one "things to try / vary" sentence.
"""


def build_system_blocks() -> list[dict]:
    """Return the system prompt as a list of TextBlockParam with cache_control.

    Stable across all turns in a session — gear lives in the first user message
    (D-11) so this function always returns the same value.
    """
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT_TEXT,
            "cache_control": {"type": "ephemeral"},
        }
    ]
```

### Pattern 4: `<sources>` XML Block Injection

**What:** Format `list[ChunkResult]` into the `<sources>` XML block that the model uses for grounded generation. Inject it into the final user message content before the user's actual question. Session-local IDs `S1..Sn` per request.

```python
# Source: CONTEXT.md D-14 + ARCHITECTURE.md — project-defined format
# app/generation/prompt.py

def build_sources_xml(sources: list[ChunkResult]) -> str:
    """Format retrieved chunks as <sources> XML for injection into user message."""
    parts = ["<sources>"]
    for i, chunk in enumerate(sources, start=1):
        parts.append(
            f'  <source id="S{i}" type="{chunk.source_type}" name="{chunk.source_name}">'
        )
        parts.append(f"    {chunk.text}")
        parts.append("  </source>")
    parts.append("</sources>")
    return "\n".join(parts)


def build_messages(
    turns: list[dict],  # prior turns: [{"role": "user"|"assistant", "content": str}, ...]
    user_message: str,
    sources: list[ChunkResult],
) -> list[dict]:
    """Build the anthropic messages array for this turn.

    History turns are included verbatim (they already contain embedded <sources>
    from prior requests — the model can see them for context).
    The current user turn injects <sources> before the user's question.
    """
    messages = list(turns)  # copy of history
    sources_xml = build_sources_xml(sources)
    messages.append({
        "role": "user",
        "content": f"{sources_xml}\n\n{user_message}",
    })
    return messages
```

### Pattern 5: In-Process Session Store with Sliding Window

**What:** A module-level `dict` keyed by `session_id` (UUID string). Each session stores a list of `{"role": "user"|"assistant", "content": str}` dicts — the raw anthropic `messages` array history. Sliding window drops oldest turn-pair (2 messages) when history exceeds `MAX_TURNS` turns (20 messages = 10 pairs).

```python
# Source: CONTEXT.md D-10, D-11, D-12 — project design decisions
# app/session.py

import threading

_sessions: dict[str, list[dict]] = {}
_lock = threading.Lock()   # single-user tool: protects against concurrent requests in theory

MAX_MESSAGES = 20   # 10 turn pairs (D-12: retain last 10–15 pairs)


def get_or_create_session(session_id: str) -> dict:
    """Return session dict, creating it if absent."""
    with _lock:
        if session_id not in _sessions:
            _sessions[session_id] = []
        return {"id": session_id, "turns": _sessions[session_id]}


def append_turn(session_id: str, role: str, content: str) -> None:
    """Append one turn to session history; apply sliding window if needed."""
    with _lock:
        turns = _sessions.setdefault(session_id, [])
        turns.append({"role": role, "content": content})
        # Sliding window: keep last MAX_MESSAGES messages
        if len(turns) > MAX_MESSAGES:
            # Drop the oldest turn PAIR (user + assistant)
            # Always drop 2 to preserve role alternation
            del turns[:2]
```

**Thread safety note:** For a single-user local tool, a `threading.Lock()` on the dict is sufficient. FastAPI + uvicorn (single-process, async) means true concurrent session writes are rare, but the lock costs nothing.

### Pattern 6: Frontend ReadableStream SSE Parser

**What:** Custom hook that opens a `fetch()` POST, reads the `ReadableStream` body with `getReader()`, decodes with `TextDecoder`, splits on `\n\n` boundaries, and dispatches parsed `event:` / `data:` lines to callbacks.

**When to use:** Any POST endpoint returning `text/event-stream`. `EventSource` is GET-only so it cannot be used with `POST /chat`.

```typescript
// Source: D-05, D-06, D-07, UI-SPEC interaction contracts — project decisions
// frontend/hooks/useSSEStream.ts

type TokenCallback = (text: string) => void;
type SessionCallback = (sessionId: string) => void;
type CitationsCallback = (sources: CitationSource[]) => void;
type ErrorCallback = (error: Error) => void;

interface CitationSource {
  id: string;        // "S1"
  chunk_id: string;  // UUID
  source_type: string;
  source_name: string;
}

async function streamChat(
  message: string,
  sessionId: string | null,
  gear: object | null,
  onSession: SessionCallback,
  onToken: TokenCallback,
  onCitations: CitationsCallback,
  onError: ErrorCallback,
  onDone: () => void,
): Promise<void> {
  const response = await fetch('/api/py/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message, gear }),
  });

  if (!response.ok || !response.body) {
    onError(new Error(`Server error: ${response.status}`));
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE messages are separated by \n\n (EventSourceResponse default sep is \r\n)
      // sse-starlette 3.4.4 default separator is \r\n — split on either
      const events = buffer.split(/\r?\n\r?\n/);
      buffer = events.pop() ?? '';  // last element may be incomplete

      for (const eventBlock of events) {
        if (!eventBlock.trim()) continue;
        const lines = eventBlock.split(/\r?\n/);

        let eventType = '';
        let dataLine = '';

        for (const line of lines) {
          if (line.startsWith('event: ')) eventType = line.slice(7).trim();
          if (line.startsWith('data: ')) dataLine = line.slice(6);
        }

        if (!dataLine) continue;

        const parsed = JSON.parse(dataLine);

        if (eventType === 'session') {
          onSession(parsed.session_id);
        } else if (eventType === 'citations') {
          onCitations(parsed.sources);
        } else {
          // Plain data: token
          if (parsed.text) onToken(parsed.text);
        }
      }
    }
  } finally {
    reader.releaseLock();
    onDone();
  }
}
```

**SSE frame format produced by sse-starlette 3.4.4 (verified):**
```
event: session\r\ndata: {"session_id": "abc-123"}\r\n\r\n
data: {"text": " warm"}\r\n\r\n
event: citations\r\ndata: {"sources": [...]}\r\n\r\n
```

### Pattern 7: GET /sources/{chunk_id} Endpoint

**What:** Fetch full chunk text and parent document metadata for citation drawer hydration. Uses `get_conn()` (existing pattern) with parameterized SQL (no f-strings).

```python
# Source: CONTEXT.md D-16 + app/retrieval/base.py patterns
# app/main.py

_SOURCES_SQL = """
    SELECT
        c.id::text         AS chunk_id,
        c.chunk_text,
        c.source_type,
        c.metadata_json,
        d.title,
        d.source_id        AS document_source_id,
        d.metadata_json    AS document_metadata_json
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE c.id = %s::uuid
"""


@app.get("/sources/{chunk_id}")
async def get_source(chunk_id: str):
    from app.db import get_conn
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(_SOURCES_SQL, (chunk_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Chunk not found")
    # ... map row to response dict
```

### Anti-Patterns to Avoid

- **Yielding raw strings from the SSE generator:** `EventSourceResponse` will wrap them as `data: <string>\r\n\r\n` — the frontend parser will try to `JSON.parse()` a bare string and fail. Always yield `ServerSentEvent(data=json.dumps({...}))`.
- **Using `client.messages.create()` with `stream=True`:** This is the lower-level API that returns a raw `AsyncStream[RawMessageStreamEvent]`. Prefer `client.messages.stream()` which wraps it in the `AsyncMessageStreamManager` context manager and provides `.text_stream`.
- **Attaching `cache_control` to the `system=` string:** The `system` parameter accepts either a plain `str` (no caching) or `Iterable[TextBlockParam]` (enables per-block cache_control). Pass the list of dicts, not a string, for caching to work.
- **Calling `register_vector(conn)` inside `generator.py`:** This is `db.py`'s responsibility (already called by `get_conn()`). Do not call it in the generation module.
- **Building SQL with f-strings:** No f-string SQL anywhere — always `%s` placeholders (CLAUDE.md hard constraint).
- **Streaming citation drawer fetch:** `GET /sources/{chunk_id}` should return a standard JSON response (not SSE). The drawer is populated synchronously from a single JSON fetch.
- **Buffering tokens before emitting:** Do not accumulate tokens server-side before yielding to the client. Stream tokens live; only accumulate in `full_response` *in parallel* (append to a list as you yield), then do citation validation after the stream ends.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSE event framing | Custom `"event: session\r\ndata: ...\r\n\r\n"` string concatenation | `ServerSentEvent(data=..., event="session")` from sse-starlette | Handles encoding, multi-line data, retry fields, separator variants |
| Anthropic streaming iteration | Manual `async for event in raw_stream` with `event.type == "content_block_delta"` checks | `AsyncMessageStream.text_stream` async iterator | Filters to text deltas only; handles all event types automatically |
| UUID generation | Custom ID scheme | `str(uuid.uuid4())` from stdlib | UUIDs are the established session identity primitive |
| Token-by-token response accumulation | Complex buffer | `full_response = []; full_response.append(text)` inside the `text_stream` loop | Dead simple; `"".join(full_response)` after stream |
| SSE client-side parsing | Third-party library | Custom `useSSEStream` hook (30 lines, pattern verified above) | `EventSource` is GET-only; the custom hook is the only viable pattern for POST SSE |

**Key insight:** The three hardest problems (SSE framing, async LLM streaming, citation validation) each have clean single-library or stdlib solutions. The custom code is only glue.

---

## Runtime State Inventory

> Phase 3 is a greenfield addition (new modules, new frontend). No rename/refactor. Skip.

---

## Common Pitfalls

### Pitfall 1: Session History Mutation During Streaming

**What goes wrong:** The session history is appended with the assistant's response *after* streaming completes. But if the SSE generator and the session append share the same mutable list reference, a concurrent request could see a partial session state.

**Why it happens:** FastAPI runs handlers concurrently. For a single-user local tool this is rare but possible (e.g., user opens two tabs).

**How to avoid:** Append the user turn before returning `EventSourceResponse`. Append the assistant turn after streaming ends — do this in a `background` task or by wrapping the generator to call `append_turn(session_id, "assistant", full_text)` as the last step before the generator returns.

**Warning signs:** Session history shows duplicate or missing turns in multi-tab scenarios.

### Pitfall 2: sse-starlette Default Ping Fires Mid-Stream

**What goes wrong:** `EventSourceResponse` sends a ping comment (`: \r\n\r\n`) every 15 seconds by default. The frontend SSE parser must ignore comment lines (lines starting with `:`).

**Why it happens:** The `DEFAULT_PING_INTERVAL = 15` in sse-starlette 3.4.4.

**How to avoid:** In the `useSSEStream` hook, skip lines starting with `:` in the SSE frame parser. Or pass `ping=0` to `EventSourceResponse(event_gen(), ping=0)` to disable pings for the streaming endpoint (acceptable since the endpoint streams continuously and pings are only needed for long-lived idle connections).

**Warning signs:** Frontend throws `JSON.parse` errors on `: ` lines.

### Pitfall 3: `async with client.messages.stream()` Raises AuthenticationError

**What goes wrong:** `AsyncAnthropic` constructed without `api_key` argument raises `AuthenticationError` at request time (not at import time).

**Why it happens:** `OpenAI(api_key=...)` must be explicitly passed from `Settings` per CLAUDE.md conventions (Phase 1 Plan 03 established this for the OpenAI client).

**How to avoid:** `AsyncAnthropic(api_key=get_settings().anthropic_api_key)`. Add `anthropic_api_key: str | None = None` to `Settings` in `app/config.py`. Fail fast in the FastAPI startup hook if `anthropic_api_key` is None.

**Warning signs:** `401 Unauthorized` from Anthropic on first request; works with env var set.

### Pitfall 4: Frontend SSE Parser Misses Tokens with `\r\n` vs `\n` Separators

**What goes wrong:** sse-starlette default separator is `\r\n` — frames are delimited by `\r\n\r\n`. If the frontend splits only on `\n\n`, it misses all events on browsers that respect `\r\n`.

**Why it happens:** The W3C SSE spec allows `\r\n`, `\r`, or `\n` as line separators. sse-starlette defaults to `\r\n`.

**How to avoid:** Split buffer on `/\r?\n\r?\n/` (regex that matches both), and split lines on `/\r?\n/`. The pattern in the Code Examples above does this correctly.

**Warning signs:** No tokens appear in the browser despite the backend emitting them; the buffer accumulates but never splits into events.

### Pitfall 5: Citation Regex Fires During Streaming

**What goes wrong:** If the post-stream regex runs against partial text (e.g., in a `setInterval` that polls `full_response`), it may find `[S1]` before the stream completes and emit citations prematurely.

**Why it happens:** Trying to be clever about early citation rendering.

**How to avoid:** Run the citation regex exactly once: after the `async with client.messages.stream()` block exits (stream complete). Per D-08, there is no early citation rendering. The `event: citations` fires after the stream ends, period.

### Pitfall 6: `model` String Not Recognized by SDK

**What goes wrong:** If `claude-sonnet-4-6` is not a valid model ID in `anthropic 0.102.0`, the API returns a 400 error. The SDK will also warn if the model is in `DEPRECATED_MODELS`.

**Why it happens:** Model ID strings change with Anthropic releases.

**How to avoid:** `claude-sonnet-4-6` was verified NOT in the `DEPRECATED_MODELS` list in `anthropic 0.102.0` (confirmed via venv inspection). It is a valid model ID as of 2026-05-19. [VERIFIED: anthropic 0.102.0 SDK installed in venv]

### Pitfall 7: `GET /sources/{chunk_id}` Returns Wrong Columns

**What goes wrong:** The chunks table has `chunk_text` (not `text`) and `metadata_json` (not `metadata`). The SQL in `GET /sources/{chunk_id}` must use exact column names from `scripts/init_db.sql`.

**Why it happens:** Column names differ from the conceptual field names in CONTEXT.md/ARCHITECTURE.md.

**How to avoid:** Use the exact column names from `init_db.sql`: `chunk_text`, `metadata_json`, `source_type`. The `source_name` field is derived from `metadata_json->>'source_filename'` (same as `_row_to_chunk_result` in `app/retrieval/base.py`).

---

## Code Examples

### Complete async generator signature (verified)
```python
# app/generation/generator.py — the generator is an async generator function
# Source: Python async generator pattern + sse-starlette 3.4.4 verified

from collections.abc import AsyncIterator
from sse_starlette.event import ServerSentEvent

async def stream_response(...) -> AsyncIterator[ServerSentEvent]:
    yield ServerSentEvent(data='{"session_id": "..."}', event="session")
    async with client.messages.stream(...) as stream:
        async for text in stream.text_stream:
            yield ServerSentEvent(data=json.dumps({"text": text}))
    # post-stream citation validation ...
    yield ServerSentEvent(data=json.dumps({"sources": [...]}), event="citations")
```

### Exact SSE encoded output (verified via `ServerSentEvent.encode()`)
```
# session event
event: session\r\n
data: {"session_id": "abc-123-..."}\r\n
\r\n

# token event (no event: line — plain data)
data: {"text": " Set"}\r\n
\r\n

# citations event
event: citations\r\n
data: {"sources": [{"id": "S1", "chunk_id": "...", "source_type": "forum", "source_name": "bb_king_tone.txt"}]}\r\n
\r\n
```

### Prompt caching via TextBlockParam (verified)
```python
# Correct: system is list[TextBlockParam dict]
system=[{"type": "text", "text": SYSTEM_PROMPT_TEXT, "cache_control": {"type": "ephemeral"}}]

# Incorrect (no caching):
system=SYSTEM_PROMPT_TEXT   # string bypasses cache_control
```

### Source type → label mapping (from CONTEXT.md)
```python
# Python (server, for SSE citations payload)
SOURCE_TYPE_LABELS = {
    "forum": "[Forum]",
    "pdf_manual": "[Manual]",
    "web_article": "[Article]",
    "youtube": "[YouTube]",
}

# TypeScript (frontend, for citation drawer badge)
const SOURCE_TYPE_LABELS: Record<string, string> = {
  forum: "[Forum]",
  pdf_manual: "[Manual]",
  web_article: "[Article]",
  youtube: "[YouTube]",
};
```

### next.config.js rewrite (from D-02)
```javascript
// frontend/next.config.js
/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/py/:path*',
        destination: 'http://localhost:8000/:path*',
      },
    ];
  },
};
module.exports = nextConfig;
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `EventSource` for SSE | `fetch() + ReadableStream.getReader()` for POST SSE | Always — EventSource is GET-only | All streaming POST endpoints need the custom fetch pattern |
| `client.messages.create(stream=True)` | `client.messages.stream()` context manager | anthropic SDK v0.3+ | Cleaner API; `.text_stream` isolates text deltas |
| Synchronous `Anthropic()` in FastAPI | `AsyncAnthropic()` for async FastAPI routes | FastAPI best practice | Avoids blocking the event loop during LLM calls |
| `system="string"` | `system=[{"type": "text", "text": "...", "cache_control": {...}}]` | anthropic SDK prompt caching feature | Reduces TTFT on follow-up turns |
| IVFFlat pgvector index | HNSW pgvector index (already done in Phase 1) | pgvector 0.5.0 | Works on empty tables; better recall at <100K chunks |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `create-next-app@latest` uses the stable Next.js 15.x line, not the 16.x pre-release | Standard Stack | Installation uses wrong version; planner should use `create-next-app` defaults, not hardcode a version |
| A2 | `claude-sonnet-4-6` is the correct model ID string for the current Sonnet 4.x model | Code Examples | API returns 400; planner should verify model ID in Anthropic's model documentation at plan time |

---

## Open Questions

1. **Session history append after streaming completes**
   - What we know: The assistant response must be appended to session history after streaming ends
   - What's unclear: Whether to use a FastAPI `BackgroundTask`, or to complete the append inside the async generator before it returns
   - Recommendation: Append inside the async generator as the last step after `event: citations` is yielded — the generator is still running at that point and has access to `full_response`. No background task needed.

2. **`anthropic_api_key` missing in production**
   - What we know: FastAPI should fail fast if the key is absent
   - What's unclear: Whether to validate at startup (`@app.on_event("startup")`) or at request time
   - Recommendation: Validate at request time in the chat handler — emit a 500 with a clear error message. Startup validation is also acceptable but adds complexity for a local single-user tool.

3. **Connection lifecycle for `GET /sources/{chunk_id}`**
   - What we know: `get_conn()` opens a new psycopg3 connection per call (no pool in Phase 3 — `app/db.py` comment: "Pooling is Phase 3's job once the FastAPI request path exists")
   - What's unclear: Whether to add a connection pool in `app/main.py` startup for Phase 3
   - Recommendation: Add a minimal async connection pool via `psycopg_pool.AsyncConnectionPool` in `app/main.py` startup. However, `psycopg_pool` is NOT installed (`psycopg[binary]` does not include it). Simpler option: use `get_conn()` per request (acceptable for a single-user local tool). **Flag for planner to decide** — installing `psycopg_pool` adds a dependency; using `get_conn()` per request is safe but creates a new connection for each API call.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All Python code | ✓ | 3.12 (venv) | — |
| PostgreSQL (Docker) | `GET /sources/{chunk_id}` | ✓ | pg17 (Docker Compose) | — |
| anthropic SDK | `app/generation/` | ✓ | 0.102.0 | — |
| sse-starlette | `app/main.py` | ✓ | 3.4.4 | — |
| fastapi | `app/main.py` | ✓ | 0.136.1 | — |
| uvicorn | Server | ✓ | 0.46.0 | — |
| Node.js | `frontend/` | ✓ | v19.6.0 | — |
| npm | `frontend/` | ✓ | 11.12.1 | — |
| ANTHROPIC_API_KEY (env var) | `app/generation/` | [ASSUMED] | — | None — blocks generation |
| psycopg_pool | Connection pooling | ✗ | — | Use `get_conn()` per request (single-user, acceptable) |
| pytest-asyncio | Async route testing | ✗ | — | Use starlette `TestClient` (sync) |

**Missing dependencies with no fallback:**
- `ANTHROPIC_API_KEY` env var — must be present in `.env` before running `POST /chat`. Add to `.env.example`.

**Missing dependencies with fallback:**
- `psycopg_pool` — fall back to `get_conn()` per request for Phase 3 (single-user, acceptable latency).
- `pytest-asyncio` — use `starlette.testclient.TestClient` which handles async routes without pytest-asyncio.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.5.0 |
| Config file | none — uses pytest discovery defaults |
| Quick run command | `venv/bin/python -m pytest tests/test_generation.py tests/test_session.py tests/test_main.py -x -q` |
| Full suite command | `venv/bin/python -m pytest -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GEN-01 | System prompt enforces grounding-only rule | unit | `pytest tests/test_generation.py::test_system_prompt_contains_grounding_rules -x` | ❌ Wave 0 |
| GEN-01 | Empty-context call returns refusal text (no fabrication) | unit | `pytest tests/test_generation.py::test_empty_sources_produces_refusal_structure -x` | ❌ Wave 0 |
| GEN-02 | Citation regex extracts `[S1]` correctly | unit | `pytest tests/test_generation.py::test_citation_regex_extracts_valid_refs -x` | ❌ Wave 0 |
| GEN-02 | Post-stream validator discards `[Sn]` where n > len(sources) | unit | `pytest tests/test_generation.py::test_citation_validator_discards_out_of_range -x` | ❌ Wave 0 |
| GEN-07 | SSE generator yields session event first | unit (mock Anthropic) | `pytest tests/test_generation.py::test_stream_yields_session_event_first -x` | ❌ Wave 0 |
| GEN-07 | SSE generator yields citations event last | unit (mock Anthropic) | `pytest tests/test_generation.py::test_stream_yields_citations_event_last -x` | ❌ Wave 0 |
| CHAT-02 | Session store creates new session on unknown session_id | unit | `pytest tests/test_session.py::test_get_or_create_creates_new_session -x` | ❌ Wave 0 |
| CHAT-02 | Session store returns existing session on known session_id | unit | `pytest tests/test_session.py::test_get_or_create_returns_existing -x` | ❌ Wave 0 |
| CHAT-02 | Sliding window drops oldest pair when history exceeds MAX_MESSAGES | unit | `pytest tests/test_session.py::test_sliding_window_drops_oldest_pair -x` | ❌ Wave 0 |
| CHAT-03 | Frontend "New chat" resets session_id to null | manual (browser) | — | — |
| CITE-01 | `GET /sources/{chunk_id}` returns chunk text + source_type | integration (Postgres) | `pytest tests/test_main.py::test_get_source_returns_chunk_text -x -m integration` | ❌ Wave 0 |
| CITE-02 | `event: citations` payload includes source_type field | unit | `pytest tests/test_generation.py::test_citations_payload_includes_source_type -x` | ❌ Wave 0 |
| CITE-03 | Coverage indicator N = len(validated_citations) | unit | `pytest tests/test_generation.py::test_citation_count_equals_validated_sources -x` | ❌ Wave 0 |
| CHAT-01/GEN-07 | `POST /chat` returns 200 and text/event-stream content-type | integration (mock Anthropic, mock retrieve) | `pytest tests/test_main.py::test_chat_endpoint_returns_event_stream -x` | ❌ Wave 0 |
| GEN-01 | No f-string SQL in `app/main.py` | static | `pytest tests/test_main.py::test_no_fstring_sql_in_main -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `venv/bin/python -m pytest tests/test_generation.py tests/test_session.py -x -q`
- **Per wave merge:** `venv/bin/python -m pytest -x -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_generation.py` — unit tests for prompt builder, citation regex, stream_response mock
- [ ] `tests/test_session.py` — unit tests for SessionStore sliding window
- [ ] `tests/test_main.py` — integration tests for `POST /chat` (mock Anthropic + mock retrieve) and `GET /sources/{chunk_id}` (live DB, skip if unreachable)

**Testing pattern for `POST /chat`:** Use `starlette.testclient.TestClient` with dependency injection to replace `retrieve()` and `AsyncAnthropic` with fakes that return known chunks and pre-determined token sequences. This matches the `_FakeEmbedder` / `_FakeConn` / `_FakeCursor` pattern established in Phase 2.

---

## Security Domain

> `security_enforcement` is not explicitly `false` in config — included per protocol.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Single-user local tool — no auth |
| V3 Session Management | Yes (in-process session dict) | UUID session IDs generated server-side via `uuid.uuid4()`; client cannot forge a valid UUID |
| V4 Access Control | No | Single-user, no multi-tenancy |
| V5 Input Validation | Yes | Pydantic `ChatRequest` model validates request body; `chunk_id` in `GET /sources/{chunk_id}` cast to `::uuid` in SQL (rejects non-UUID strings) |
| V6 Cryptography | No | No secrets stored; API keys are env vars |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via `chunk_id` path param | Tampering | `WHERE c.id = %s::uuid` — parameterized + UUID cast rejects injection |
| ANTHROPIC_API_KEY leakage in logs | Information Disclosure | Never log `settings.anthropic_api_key`; `repr(e)` not `traceback.format_exc()` in error handlers (established in Phase 1 Plan 04) |
| Session ID forgery | Elevation of Privilege | Acceptable for a single-user local tool — no sensitive data in sessions |
| LLM prompt injection via user message | Tampering | System prompt is stable and cannot be overridden by user content injected into `<sources>` XML (XML is model-readable, not model-executable); acceptable risk for personal tool |

---

## Sources

### Primary (HIGH confidence)

- `anthropic 0.102.0` venv source — `lib/streaming/_messages.py` — AsyncMessageStream.text_stream, text_stream async iterator, `get_final_message()` method verified
- `anthropic 0.102.0` venv source — `resources/messages/messages.py` — AsyncMessages.stream() signature, cache_control parameter, system parameter type
- `anthropic 0.102.0` venv source — `types/__init__.py` — CacheControlEphemeralParam, TextBlockParam with cache_control field
- `sse-starlette 3.4.4` venv source — EventSourceResponse.__init__ signature, ensure_bytes() handling of dict/ServerSentEvent/str
- `sse-starlette 3.4.4` venv source — ServerSentEvent.__init__ and encode() — verified wire format `event: <name>\r\ndata: <payload>\r\n\r\n`
- `scripts/init_db.sql` — chunks table exact column names (`chunk_text`, `metadata_json`, `source_type`)
- `app/retrieval/base.py` — ChunkResult frozen dataclass fields verified
- `app/config.py` — Settings class (verified fields; `anthropic_api_key` not yet present)
- `.planning/phases/03-grounded-generation-minimal-chat-ui/03-CONTEXT.md` — all locked decisions D-01 through D-17
- `.planning/phases/03-grounded-generation-minimal-chat-ui/03-UI-SPEC.md` — approved UI contract
- npm registry — `next` 16.2.6, `tailwindcss` 4.3.0, `lucide-react` 1.16.0, `typescript` 6.0.3 verified via `npm view`

### Secondary (MEDIUM confidence)

- `.planning/research/ARCHITECTURE.md` — generation architecture, session memory design, API shapes (MEDIUM: authored 2026-05-13, pre-Phase 2; still accurate for Phase 3)
- `.planning/research/STACK.md` — pinned versions reference (HIGH for version numbers; MEDIUM for behavioral claims)

### Tertiary (LOW confidence — training data only)

- Next.js App Router + ReadableStream SSE hook patterns — [ASSUMED] standard pattern; not verified against a running Next.js instance
- `create-next-app` scaffolded version number — [ASSUMED] 15.x stable; use `create-next-app@latest` defaults at implementation time

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all Python packages verified in venv; npm versions verified via `npm view`
- Architecture patterns: HIGH — event format verified via `ServerSentEvent.encode()` in venv; streaming patterns verified from SDK source
- Pitfalls: HIGH for server-side (verified from SDK/sse-starlette source); MEDIUM for frontend (pattern verified, not run in a browser)
- Validation architecture: HIGH — follows established project test patterns exactly

**Research date:** 2026-05-19
**Valid until:** 2026-06-19 (30 days for stable; Next.js version claim valid for 7 days — use `create-next-app@latest` at implementation time)
