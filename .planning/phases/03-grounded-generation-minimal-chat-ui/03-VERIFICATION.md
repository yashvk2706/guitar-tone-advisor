---
phase: 03-grounded-generation-minimal-chat-ui
verified: 2026-05-21T00:00:00Z
status: human_needed
score: 14/15 must-haves verified
overrides_applied: 0
human_verification:
  - test: "End-to-end streaming with real Anthropic API + live DB"
    expected: "Tokens stream into the assistant bubble in real time; [S1] [S2] citation pills appear after streaming ends; clicking a pill opens the citation drawer with [Forum] badge and raw chunk text; coverage indicator shows 'N sources agree'"
    why_human: "Requires ANTHROPIC_API_KEY, running Postgres with corpus data, FastAPI server, and Next.js dev server; cannot be verified programmatically without live API calls"
  - test: "Refusal behavior when corpus is silent (SC-2)"
    expected: "With empty retrieval results, response contains a refusal phrase like 'I don't have material on ...' rather than fabricated knob settings or gear names"
    why_human: "Depends on actual LLM behavior given the system prompt grounding rules; cannot be verified without a live Anthropic API call"
  - test: "Gear translation phrasing (SC-3)"
    expected: "When the user's gear differs from corpus gear (e.g., user has Katana, corpus has JCM800), response contains gear-translation phrasing"
    why_human: "LLM behavioral output — requires live call with specific gear mismatch query"
  - test: "Concrete knob positions in response (GEN-03, GEN-04)"
    expected: "When corpus chunks contain knob settings, response includes values on 0-10 scale (e.g., Bass=7 Mid=4 Treble=6) and/or signal-chain order"
    why_human: "Requires corpus with knob-position data and a live LLM call to verify the model follows the FORMAT block in the system prompt"
---

# Phase 3: Grounded Generation & Minimal Chat UI — Verification Report

**Phase Goal:** A guitarist opens the web app, types their gear + a target tone, and watches a streamed, cited recommendation appear — with [S{n}] markers that open a drawer showing the actual forum-post text, and a refusal-with-reason whenever the corpus is silent.
**Verified:** 2026-05-21
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | System prompt enforces all three grounding rules (cite every recommendation, refuse with reason when corpus is silent, never cite a source not in sources) | VERIFIED | `app/generation/prompt.py` lines 34, 36, 39: "cite it inline as [Sn]", "refuse plainly:", "Never cite a source not in the <sources> block" — all three D-13 phrases present verbatim |
| 2 | build_sources_xml() formats list[ChunkResult] into sources XML with S1..Sn IDs, type=, and name= attributes | VERIFIED | `prompt.py` lines 103–112: loop over sources with `id="S{i}" type="{chunk.source_type}" name="{chunk.source_name}"`. Empty list returns `<sources>\n</sources>` at line 102 |
| 3 | stream_response() yields event: session first, then plain data: token events, then event: citations last | VERIFIED | `generator.py` lines 77–116: session SSE at line 77–80, token loop at line 93–95, citations SSE at line 113–116 — ordering enforced by code structure |
| 4 | Post-stream citation validator discards [Sn] references where n > len(sources) | VERIFIED | `generator.py` line 100: `valid_ns = {n for n in raw_ns if 1 <= n <= len(sources)}` — out-of-range indices silently dropped |
| 5 | event: citations payload contains source_type field for every valid citation | VERIFIED | `generator.py` line 106: `"source_type": sources[n - 1].source_type` included in each citation dict |
| 6 | Coverage count N equals len(validated citations) | VERIFIED | `CoverageIndicator.tsx` receives `count={message.citations.length}` from `MessageBubble.tsx` — citations array is the validated set from the citations SSE payload |
| 7 | get_or_create_session() creates a new empty session dict when called with an unknown session_id | VERIFIED | `session.py` lines 63–65: creates empty list if session_id not in _sessions |
| 8 | Sliding window drops the oldest turn pair (2 messages) when len(turns) exceeds MAX_MESSAGES (20) | VERIFIED | `session.py` lines 90–91: `del turns[:2]` when `len(turns) > MAX_MESSAGES` |
| 9 | Module-level _sessions dict is thread-safe via threading.Lock | VERIFIED | `session.py` lines 37, 62, 86: `_lock = threading.Lock()` with `with _lock:` in both public functions |
| 10 | POST /chat returns HTTP 200 with Content-Type: text/event-stream | VERIFIED | `main.py` line 160: `EventSourceResponse(event_gen(), ping=0)` — sse-starlette returns text/event-stream; confirmed by `test_chat_endpoint_returns_event_stream` passing |
| 11 | GET /sources/{chunk_id} returns 404 for an unknown chunk_id | VERIFIED | `main.py` lines 192–193: `raise HTTPException(status_code=404, detail="Chunk not found")` when row is None; also catches DataError for invalid UUID at line 183–186 |
| 12 | /api/py/* requests proxy to localhost:8000 via next.config.js rewrites | VERIFIED | `next.config.js` lines 3–10: `source: '/api/py/:path*'`, `destination: 'http://localhost:8000/:path*'` |
| 13 | Citation pills [S1], [S2] appear below assistant bubble ONLY after citations SSE fires (not during streaming) | VERIFIED | `MessageBubble.tsx` line 61: `message.citations !== undefined && !message.isStreaming` gate; `ChatPage.tsx` onCitations callback at line 113–119 sets `isStreaming: false` while setting citations |
| 14 | Clicking a citation pill triggers fetch to GET /api/py/sources/{chunk_id} and opens drawer with source-type badge and chunk text | VERIFIED | `ChatPage.tsx` line 55: `fetch('/api/py/sources/${chunkId}')` in `handleCitationClick`; `CitationDrawer.tsx` renders badge from `SOURCE_TYPE_BADGE_CLASSES` map and `{drawer.data.chunk_text}` as JSX text |
| 15 | Streamed response behavior with actual Anthropic API | UNCERTAIN (human needed) | Requires live ANTHROPIC_API_KEY + corpus in DB; SSE plumbing is fully wired but LLM behavioral contract (grounding, refusal, gear translation, knob positions) cannot be verified without a live call |

**Score:** 14/15 truths verified (1 uncertain — deferred to human verification)

---

### Roadmap Success Criteria Coverage

| SC | Criterion | Status | Evidence |
|----|-----------|--------|----------|
| SC-1 | BB King query yields streamed answer with [Sn] citation; clicking citation opens drawer with forum-post chunk and [Forum] label | UNCERTAIN (human needed) | All plumbing is wired; requires live API call + corpus data |
| SC-2 | Empty retrieval produces refusal with reason, not fabricated answer | UNCERTAIN (human needed) | System prompt grounding rules are implemented; LLM adherence requires live verification |
| SC-3 | Response contains concrete knob positions and/or signal-chain order; gear-translation phrasing when gear differs | UNCERTAIN (human needed) | System prompt FORMAT block and GEAR TRANSLATION section are present; LLM behavioral output requires live verification |
| SC-4 | "New chat" button clears in-process session memory; subsequent messages have no recollection of prior turns | VERIFIED | `ChatPage.tsx` `handleNewChat()` (lines 162–172): `setSessionId(null)`, `setMessages([])`, `setDrawer(null)`, `setIsStreaming(false)` — client-only reset per D-17; `session.py` `get_or_create_session()` creates new session when session_id is null→new UUID |
| SC-5 | Coverage indicator shows how many distinct sources support each answer | VERIFIED | `CoverageIndicator.tsx`: returns null for N=0, "1 source" for N=1, "N sources agree" for N>1; wired via `MessageBubble.tsx` |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/config.py` | anthropic_api_key field on Settings | VERIFIED | Line 36: `anthropic_api_key: str | None = None` — after openai_api_key field |
| `app/generation/__init__.py` | Empty package marker | VERIFIED | File exists, empty |
| `app/generation/prompt.py` | build_system_blocks, build_sources_xml, build_messages, SYSTEM_PROMPT_TEXT | VERIFIED | All 4 exports present and substantive |
| `app/generation/generator.py` | stream_response() async generator yielding ServerSentEvent | VERIFIED | 117 lines, full implementation with _CITATION_RE, post-stream validator, SSE sequence |
| `app/session.py` | get_or_create_session, append_turn, MAX_MESSAGES | VERIFIED | All three exports present; threading.Lock, sliding window at del turns[:2] |
| `app/main.py` | FastAPI app with POST /chat, GET /sources/{chunk_id}, GET /health | VERIFIED | 210 lines; all three endpoints implemented; _SOURCES_SQL module-level constant |
| `frontend/next.config.js` | /api/py/:path* → http://localhost:8000/:path* rewrite | VERIFIED | Lines 3–10: rewrite present, CommonJS module.exports |
| `frontend/hooks/useSSEStream.ts` | ReadableStream SSE parser with callbacks | VERIFIED | 110 lines; /r?\n\r?\n/ frame splitting, ':' ping skipping, session/token/citations/error/done dispatch |
| `frontend/components/ChatPage.tsx` | Top-level orchestration with all state | VERIFIED | 254 lines; sessionId, messages, isStreaming, drawer state; New Chat button; auto-scroll; Enter-to-submit |
| `frontend/components/MessageBubble.tsx` | User/assistant/error bubble variants | VERIFIED | 79 lines; ▋ streaming cursor via after:content-['▋']; deferred citation rendering |
| `frontend/components/CitationPill.tsx` | Clickable [Sn] pill | VERIFIED | 19 lines; blue Tailwind classes per UI-SPEC §4 |
| `frontend/components/CitationDrawer.tsx` | Right-side overlay with source-type badge and chunk text | VERIFIED | 108 lines; SOURCE_TYPE_BADGE_CLASSES map; backdrop; skeleton loading; JSX text rendering (no dangerouslySetInnerHTML) |
| `frontend/components/CoverageIndicator.tsx` | "N sources agree" indicator | VERIFIED | 21 lines; null for N=0, "1 source" for N=1, "N sources agree" for N>1 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `app/generation/prompt.py` | `app/retrieval/base.py` | ChunkResult import | VERIFIED | Line 20: `from app.retrieval.base import ChunkResult` |
| `app/generation/generator.py` | anthropic.AsyncAnthropic | async with client.messages.stream() | VERIFIED | Lines 86–95: `async with client.messages.stream(...)` with text_stream iteration |
| `app/generation/generator.py` | sse_starlette.event.ServerSentEvent | yield ServerSentEvent(...) | VERIFIED | Lines 77, 95, 113: three yield ServerSentEvent calls |
| `app/main.py` | `app/generation/generator.py` | stream_response() called inside event_gen() | VERIFIED | Line 30: `from app.generation.generator import stream_response`; line 138: async for loop over stream_response() |
| `app/main.py` | `app/session.py` | get_or_create_session + append_turn | VERIFIED | Line 33: `from app.session import append_turn, get_or_create_session`; lines 113, 129, 157: both functions called |
| `app/main.py` | `app/retrieval/base.py` | retrieve() called before prompt building | VERIFIED | Line 32: `from app.retrieval.base import retrieve`; line 122: `sources = retrieve(user_content, k=8)` |
| `app/main.py` | chunks table via get_conn() | _SOURCES_SQL with %s::uuid | VERIFIED | Lines 42–53: _SOURCES_SQL constant; lines 178–188: get_conn() per-request with try/finally |
| `frontend/hooks/useSSEStream.ts` | POST /api/py/chat | fetch with session_id, message, gear | VERIFIED | Lines 29–33: `fetch('/api/py/chat', {method: 'POST', ...})` |
| `frontend/components/CitationDrawer.tsx` | GET /api/py/sources/{chunk_id} | fetch on pill click (via ChatPage.tsx) | VERIFIED | `ChatPage.tsx` line 55: `fetch('/api/py/sources/${chunkId}')` in handleCitationClick; result passed as DrawerState to CitationDrawer |
| `frontend/next.config.js` | http://localhost:8000 | async rewrites() | VERIFIED | Lines 3–10: source '/api/py/:path*', destination 'http://localhost:8000/:path*' |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `ChatPage.tsx` | messages (assistant content) | streamChat() → onToken callbacks → state updates | Real tokens from SSE stream (requires live API); plumbing is connected | FLOWING (plumbing verified; live data requires human check) |
| `ChatPage.tsx` | messages.citations | streamChat() → onCitations callback → citations SSE event | Real citations from generator.py post-stream validator | FLOWING (plumbing verified) |
| `CitationDrawer.tsx` | drawer.data.chunk_text | fetch /api/py/sources/{chunk_id} → GET /sources route → Postgres | Real DB data via _SOURCES_SQL query | FLOWING (plumbing verified; requires live DB) |
| `CoverageIndicator.tsx` | count | message.citations.length | Length of validated citations array from citations SSE | FLOWING (derived from citations array) |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 15 phase-3 tests pass | `venv/bin/python -m pytest tests/test_generation.py tests/test_session.py tests/test_main.py -x -q` | 15 passed, 1 warning (PytestUnknownMarkWarning for pytest.mark.integration) | PASS |
| FastAPI app imports without error | Verified via test_chat_endpoint_returns_event_stream using TestClient | TestClient successfully instantiates app | PASS |
| No openai direct import in generation module | `grep -rn "openai" app/generation/` | Only appears in comments (not import statements) | PASS |
| No register_vector call in generator.py | `grep -n "register_vector" app/generation/generator.py` | Only appears in docstring comment (not code) | PASS |
| No f-string SQL in main.py | `test_no_fstring_sql_in_main` test passes | Line 117 has an f-string for gear JSON injection (not SQL); _SOURCES_SQL uses %s::uuid | PASS |
| next.config.js proxy rewrite present | `grep -c "api/py" frontend/next.config.js` | Returns 1 | PASS |
| dangerouslySetInnerHTML absent from CitationDrawer | grep search | No matches — chunk_text rendered as JSX text | PASS |

---

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|------------|-------------|--------|----------|
| GEN-01 | Claude generates recommendations from retrieved passages only | UNCERTAIN (human needed) | System prompt grounding rules implemented; LLM adherence requires live call |
| GEN-02 | Responses include inline [S1], [S2] citations | UNCERTAIN (human needed) | Citation format enforced by system prompt rule 1; LLM behavioral output requires live verification |
| GEN-03 | Responses include concrete knob positions 0-10 when corpus supports it | UNCERTAIN (human needed) | FORMAT block in SYSTEM_PROMPT_TEXT specifies "Bass=7 Mid=4 Treble=6" style; LLM adherence requires live call |
| GEN-04 | Responses include signal-chain order when relevant | UNCERTAIN (human needed) | FORMAT block includes "Guitar → pedals → amp" instruction; LLM behavioral output requires live call |
| GEN-05 | Gear translation when user gear differs from corpus gear | UNCERTAIN (human needed) | GEAR TRANSLATION section in SYSTEM_PROMPT_TEXT; LLM behavioral output requires live call |
| GEN-06 | Refusal with reason when corpus lacks material | UNCERTAIN (human needed) | System prompt rule 2: "refuse plainly: 'I don't have material on [X]'"; build_sources_xml([]) returns empty sources; LLM adherence requires live call |
| GEN-07 | Responses stream token-by-token; citations sent as out-of-band payload after stream | VERIFIED | stream_response() yields session→tokens→citations SSE events; app/main.py EventSourceResponse wires this to POST /chat |
| CHAT-01 | User can type gear + tone and receive grounded recommendation | VERIFIED (plumbing) / UNCERTAIN (LLM behavior) | Full UI-to-backend path is wired; requires live API for full validation |
| CHAT-02 | Per-session conversation history maintained | VERIFIED | app/session.py with threading.Lock + sliding window; app/main.py calls get_or_create_session + append_turn |
| CHAT-03 | "New chat" button clears session history | VERIFIED | ChatPage.tsx handleNewChat() resets sessionId to null + clears messages; new session UUID created on next POST /chat |
| CITE-01 | [Sn] citations are clickable and open drawer with raw chunk text | VERIFIED | CitationPill onClick → ChatPage handleCitationClick → fetch /api/py/sources → CitationDrawer with chunk_text |
| CITE-02 | Citation displays source-type label [Forum]/[Manual]/[Article]/[YouTube] | VERIFIED | CitationDrawer SOURCE_TYPE_LABELS + SOURCE_TYPE_BADGE_CLASSES maps; all four source types present |
| CITE-03 | Corpus coverage indicator shows how many sources support answer | VERIFIED | CoverageIndicator.tsx: null/N=0, "1 source", "N sources agree" |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `app/main.py` | 117 | f-string: `f"<gear>{json.dumps(req.gear)}</gear>\n\n{req.message}"` | INFO | NOT a SQL f-string — this is a gear block injected into the user message content. Static test `test_no_fstring_sql_in_main` passes because the regex specifically targets SQL interpolation patterns. Acceptable. |
| `tests/test_main.py` | 122 | `pytest.mark.integration` unregistered mark | WARNING | PytestUnknownMarkWarning — not a BLOCKER; test runs correctly. Minor tech debt but no formal issue reference. |

No TBD, FIXME, or XXX markers found in any phase-3 modified files.

---

### Human Verification Required

#### 1. Streaming Recommendation with Citations (SC-1)

**Test:** Start Postgres, run `venv/bin/python -m uvicorn app.main:app --reload` (port 8000), run `cd frontend && npm run dev` (port 3000), open http://localhost:3000. Type "I have a Fender Strat and Vox AC30. What amp settings did BB King use?" and press Enter.
**Expected:** Assistant bubble appears immediately with ▋ cursor; tokens stream in; after stream ends, [S1] [S2] etc. pills appear below the bubble (not during streaming); "N sources agree" coverage indicator appears; clicking a pill opens the right-side drawer with [Forum] badge and raw chunk text.
**Why human:** Requires ANTHROPIC_API_KEY environment variable, running Postgres with ingested forum corpus, and live API calls to the Anthropic streaming endpoint.

#### 2. Refusal Behavior When Corpus Is Silent (SC-2)

**Test:** With the app running, send a query about gear not present in the forum corpus (e.g., "What settings for a Roland JC-120 with an '80s Fender Strat to get a Dire Straits tone?" — assuming this is not in the corpus).
**Expected:** Response contains phrasing like "I don't have material on [X] — the closest I have is [Y], want that instead?" rather than fabricated knob settings or gear recommendations. No [Sn] citation pills appear.
**Why human:** LLM behavioral adherence to the system-prompt grounding rule 2 must be observed at runtime.

#### 3. Gear Translation Phrasing (SC-3, GEN-05)

**Test:** Send a query referencing gear that differs from the corpus gear (e.g., "I have a Boss Katana 50 — what settings for a warm BB King tone?" when corpus refers to Vox/Marshall).
**Expected:** Response includes a gear-translation note mapping the source gear settings to the user's Katana, e.g., "The Vox AC30 equivalent on a Boss Katana would be..."
**Why human:** LLM adherence to the GEAR TRANSLATION section of the system prompt requires live execution.

#### 4. Concrete Knob Positions in Response (GEN-03, GEN-04)

**Test:** Send a query where the corpus chunks contain EQ/knob settings (e.g., "What amp settings for a Hendrix-style tone with a Strat through a Marshall?").
**Expected:** Response includes knob-position values in the Bass=N Mid=N Treble=N format and/or signal-chain order like "Guitar → Wah → Fuzz → Marshall".
**Why human:** Depends on corpus content and LLM adherence to the FORMAT block in the system prompt.

---

### Gaps Summary

No blocker gaps found. All required code artifacts exist with substantive implementations, all critical wiring paths are connected and verified programmatically, and all 15 automated tests pass.

The 4 human verification items are not defects — they reflect the fundamental nature of LLM behavioral testing: the generation contracts (grounding, refusal, gear translation, format adherence) are correctly programmed into the system prompt, but their execution depends on the Anthropic API and live corpus data, which cannot be verified by grep or static analysis.

The one WARNING anti-pattern (`pytest.mark.integration` unregistered) is minor and does not affect test execution.

---

_Verified: 2026-05-21_
_Verifier: Claude (gsd-verifier)_
