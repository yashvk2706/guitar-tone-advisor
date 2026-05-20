# Phase 3: Grounded Generation & Minimal Chat UI - Context

**Gathered:** 2026-05-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the full end-to-end slice: Anthropic SDK streaming generation (grounded, cited, with refusal) → FastAPI SSE chat endpoint → in-process session memory → minimal Next.js chat UI with citation drawer.

**In scope:** `app/generation/` module (system prompt, `<sources>` XML injection, `[S{n}]` streaming, post-stream citation validation, refusal path), `app/main.py` FastAPI app (`POST /chat`, `GET /sources/{chunk_id}`, `GET /health`), `app/session.py` (in-process session dict, sliding-window turn management), `frontend/` Next.js app (App Router, TypeScript, Tailwind, chat UI, citation drawer, "New chat" button).

**Out of scope:** PDF/article/YouTube ingestion (later phase), hybrid tsvector+RRF retrieval (Phase 5), UI Polish features (Phase 4: rotary knobs, Markdown renderer, follow-up buttons, copy-to-clipboard, loading indicators), RAGAS eval (Phase 5), DELETE /sessions endpoint (deferred — frontend generates a fresh session_id on "New chat" instead).

</domain>

<decisions>
## Implementation Decisions

### Next.js Frontend Setup
- **D-01:** **App Router + TypeScript + Tailwind CSS only.** No CSS Modules for Phase 3. `create-next-app` defaults (App Router, TypeScript) with Tailwind CSS added. CSS Modules can be layered in Phase 4 if rotary knob or Markdown components justify the overhead.
- **D-02:** Next.js app lives in `frontend/` directory (mirrors `app/` for the Python package — keeps the root clean). Dev command: `cd frontend && npm run dev`. `frontend/next.config.js` configures the `/api/py/*` → `localhost:8000` rewrites.

### Anthropic Model for Generation
- **D-03:** Use **`claude-sonnet-4-6`** (current Sonnet 4.x). Temperature **0.0–0.2** (0.1 as default). Strong citation grounding with acceptable streaming latency (~1–2s for 400-token answer). Escalate to `claude-opus-4-7` only if Phase 5 eval reveals systematic citation violations that post-stream validation doesn't catch.
- **D-04:** Prompt caching is a viable optimization: the system prompt is stable across all turns in a session (gear lives in the first user message as a `<gear>` block, not the system prompt). Add `cache_control: {"type": "ephemeral"}` to the system prompt when the anthropic SDK supports it to reduce TTFT on follow-up turns.

### SSE Streaming Architecture
- **D-05:** **Fetch + ReadableStream** — custom hook in Next.js, no external dependencies (Vercel AI SDK is explicitly out — same category as LangChain/LlamaIndex for this project). `EventSource` is ineligible (GET-only; `/chat` is POST).
- **D-06:** SSE event sequence from FastAPI:
  1. `event: session` — payload: `{"session_id": "<uuid>"}` — emitted first, even if session_id was provided in request (idempotent)
  2. Token chunks — `data: {"text": "<token>"}` (or `data: <token>` raw) — emitted as Claude streams
  3. `event: citations` — payload: `{"sources": [{"id": "S1", "chunk_id": "<uuid>", "source_type": "forum", "source_name": "bb_king_tone.txt"}, ...]}` — emitted after stream completes and citation validation runs
- **D-07:** Session ID delivery: client sends `{"session_id": null}` on first turn, API returns a UUID in `event: session`. Client persists the UUID in React state and sends it on every subsequent turn. No cookies, no headers.

### Citation Enforcement
- **D-08:** **Post-stream validation, stream-live variant.** Tokens stream to the client in real time (no buffering). After the stream completes, the generator module accumulates the full response text, extracts all `[Sn]` references via regex, filters to `n <= len(retrieved_chunks)`, and emits **only valid source IDs** in the `event: citations` payload. Invalid `[Sn]` references in the streamed text will not be clickable (no pill rendered in the UI since they're absent from the citations payload). No response text correction.
- **D-09:** Citation regex pattern: `r'\[S(\d+)\]'` — match all occurrences, collect unique n values, discard where `int(n) > len(sources)`. The sources list is the `list[ChunkResult]` passed to the generator — no re-query to DB at validation time.

### Session Memory
- **D-10 (from ARCHITECTURE.md — locked):** In-process Python dict keyed by `session_id` (UUID). No Redis, no DB storage. Server restart clears all sessions — acceptable for a personal local tool.
- **D-11 (from ARCHITECTURE.md — locked):** Gear context lives in the first user message as a `<gear>` block (e.g., `<gear>Fender Strat, Vox AC30, TS9</gear>`). System prompt references it but does not embed it. This keeps the system prompt stable for prompt caching.
- **D-12 (from ARCHITECTURE.md — locked):** Sliding window: retain the last 10–15 turn pairs (20–30 messages). If a session exceeds budget, drop the oldest turn pair. No summarization step.

### System Prompt & Generation Module
- **D-13:** System prompt must enforce three hard rules:
  1. Every concrete recommendation (amp setting, pedal, signal chain) must be supported by a `<sources>` entry — cite it inline with `[Sn]`.
  2. When the corpus lacks material for a query, refuse with a reason: "I don't have material on [X] — the closest I have is [Y], want that instead?"
  3. Never cite a source not in the `<sources>` block. `n` in `[Sn]` must be 1 ≤ n ≤ N where N = number of sources provided.
- **D-14:** `<sources>` XML block format (injected into the final user message before generation):
  ```xml
  <sources>
    <source id="S1" type="forum" name="bb_king_tone.txt">
      [chunk text here]
    </source>
    <source id="S2" type="forum" name="evh_tone.txt">
      [chunk text here]
    </source>
  </sources>
  ```
  IDs are session-local (S1..Sn per request, not global). Stable within one turn.

### FastAPI Endpoint Design
- **D-15 (from ARCHITECTURE.md — locked):** `POST /chat` request body: `{"session_id": "uuid-or-null", "message": "...", "gear": {...}}` where `gear` is optional (only on first turn).
- **D-16:** `GET /sources/{chunk_id}` returns full chunk text + parent document metadata for citation drawer hydration. Drawer fetches this on click; the `event: citations` payload provides the chunk_ids to use.
- **D-17:** `DELETE /sessions/{session_id}` is deferred — frontend handles "New chat" by generating a fresh UUID client-side and ignoring the old session (which expires on server restart). No endpoint needed for Phase 3.

### Claude's Discretion
- Module placement: `app/generation/__init__.py`, `app/generation/prompt.py` (system prompt builder), `app/generation/generator.py` (streaming + citation validation). Mirrors `app/retrieval/` and `app/embeddings/` structure.
- Exact `sse-starlette` event format (e.g., `EventSourceResponse` constructor, generator function signature) — defer to `sse-starlette` 3.4.4 docs.
- `frontend/` directory structure within Next.js — standard `app/` (App Router), `components/`, `hooks/` layout.
- Coverage indicator wording (e.g., "3 sources agree") — implementation choice.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Scope
- `.planning/REQUIREMENTS.md` §Generation (GEN-01 through GEN-07), §Chat & Conversation (CHAT-01 through CHAT-03), §Citations & Grounding (CITE-01 through CITE-03) — all Phase 3 acceptance criteria
- `.planning/ROADMAP.md` §Phase 3 — 4 planned plans, success criteria, UI hint: yes

### Architecture (MANDATORY)
- `.planning/research/ARCHITECTURE.md` §Generation Architecture — system prompt template, `<sources>` XML format, streaming SSE schema, session memory design, sliding window rules, gear-in-first-message decision
- `.planning/research/ARCHITECTURE.md` §API Design — `/chat` request/response schema, `/sources/{chunk_id}` response shape, session_id lifecycle
- `.planning/research/ARCHITECTURE.md` §Session Memory — in-process dict, no Redis, acceptable restart behavior

### Phase 1 & 2 Established Patterns (MANDATORY)
- `app/config.py` — `get_settings()` singleton; all env vars (DATABASE_URL, OPENAI_API_KEY, EMBEDDING_MODEL, DEBUG) accessed through this
- `app/db.py` — `get_conn()` pattern; generation module's `/sources` endpoint uses this to fetch chunk text
- `app/retrieval/base.py` — `ChunkResult` frozen dataclass (chunk_id, source_type, source_name, chunk_index, text, distance); generation layer receives `list[ChunkResult]` and formats as `<sources>` XML
- `app/embeddings/base.py` — `Embedder` Protocol; `app/embeddings/factory.py` — `get_embedder()` factory
- `CLAUDE.md` §Conventions — no direct openai import; no f-string SQL; frozen dataclasses at module boundaries; `embed_query()` and `embed_documents()` always separate

### Stack
- `.planning/research/STACK.md` §Recommended Stack Summary — pinned versions: `anthropic 0.102`, `sse-starlette 3.4.4`, `fastapi 0.136`, `uvicorn`
- `.planning/research/FEATURES.md` — feature rationale for citations, streaming, session memory

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/retrieval/base.retrieve()` — takes a user query string, returns `list[ChunkResult]`; the generation layer calls this and receives the sources it needs to format as `<sources>` XML
- `app/retrieval/base.ChunkResult` — `source_type` field is already typed as `'forum'` | `'pdf_manual'` | `'web_article'` | `'youtube'`; maps directly to CITE-02 display labels `[Forum]` / `[Manual]` / `[Article]` / `[YouTube]`
- `app/config.get_settings()` — generation module uses `settings.anthropic_api_key` (to be added to Settings); `settings.embedding_model` for retrieval
- `app/db.get_conn()` — `GET /sources/{chunk_id}` fetches chunk text + metadata_json from `chunks` table via this

### Established Patterns
- **Frozen dataclass at module boundary** — generation module may expose a `GenerationResult` or similar; follow `ChunkResult` / `EmbeddingResult` convention
- **Injectable dependencies** — retrieval tests inject `conn=` and `embedder=`; generation tests should inject `anthropic_client=` and `retriever=` for offline testing
- **No f-string SQL** — the `/sources/{chunk_id}` endpoint queries the DB; use `%s` placeholders
- **`get_settings()` for all config** — add `anthropic_api_key: str | None = None` to Settings (same pattern as `openai_api_key`)
- **`app/retrieval/__init__.py` is empty** — generation module should follow the same package structure: `app/generation/__init__.py` (empty), logic in submodules

### Integration Points
- **Input to generation:** `list[ChunkResult]` from `app/retrieval/base.retrieve()` + conversation history from `app/session.py`
- **Output from generation:** SSE stream of tokens → `event: citations` payload with validated source IDs
- **Source drawer:** `GET /sources/{chunk_id}` reads `chunks` table (chunk_id UUID → chunk_text + metadata_json + source_type). chunk_ids come from `ChunkResult.chunk_id` stored server-side in the citations mapping
- **Session memory:** `app/session.py` keyed by UUID string; generation module reads history before building the messages list and appends new turn after streaming completes
- **Next.js proxy:** `frontend/next.config.js` rewrites `/api/py/*` → `http://localhost:8000/*`; frontend calls `/api/py/chat` which proxies to `localhost:8000/chat`

</code_context>

<specifics>
## Specific Ideas

- `ChunkResult.source_type` to citation label mapping: `{"forum": "[Forum]", "pdf_manual": "[Manual]", "web_article": "[Article]", "youtube": "[YouTube]"}` — hardcode this in the frontend citation pill component or the SSE citations payload.
- The `event: citations` payload should include enough data for the drawer to render without a second fetch on the fast path: `{id: "S1", chunk_id: "<uuid>", source_type: "forum", source_name: "bb_king_tone.txt"}`. The full chunk text is fetched lazily via `GET /sources/{chunk_id}` only when the user clicks the citation pill.
- Citation regex for post-stream validation: `re.findall(r'\[S(\d+)\]', response_text)` — collect unique int values, discard `n > len(sources)`. Simple and fast.
- Coverage indicator (ROADMAP success criterion 5): "N sources agree" where N = `len(validated_citations)`. Compute from the post-stream citations set.
- "New chat" in Next.js: `useState` for `sessionId`, reset to `null` on button click. The next `POST /chat` call with `session_id: null` starts a fresh session.

</specifics>

<deferred>
## Deferred Ideas

- `DELETE /sessions/{session_id}` endpoint — not needed; frontend generates a fresh UUID client-side on "New chat". Old sessions expire on server restart.
- CSS Modules — deferred to Phase 4 if rotary knob SVG or Markdown components prove difficult to style with Tailwind utilities alone.
- `neighbor_chunks` in `/sources/{chunk_id}` response (ARCHITECTURE.md "nice-to-have") — deferred to a later phase.
- Upgrade to `claude-opus-4-7` if Phase 5 eval reveals systematic citation violations post post-stream validation.

</deferred>

---

*Phase: 3-Grounded-Generation-Minimal-Chat-UI*
*Context gathered: 2026-05-19*
