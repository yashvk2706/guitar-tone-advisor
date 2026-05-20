# Phase 3: Grounded Generation & Minimal Chat UI - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-19
**Phase:** 03-grounded-generation-minimal-chat-ui
**Areas discussed:** Next.js setup, Claude model for generation, SSE consumption in Next.js, Citation enforcement strictness

---

## Next.js Setup

| Option | Description | Selected |
|--------|-------------|----------|
| Tailwind only | App Router + TypeScript + Tailwind CSS. Fastest to scaffold. CSS Modules can be added in Phase 4 if needed. | ✓ |
| Tailwind + CSS Modules | App Router + TypeScript + Tailwind with CSS Modules for component scoping from the start. | |

**User's choice:** Tailwind only (App Router + TypeScript + Tailwind CSS)
**Notes:** CSS Modules explicitly deferred to Phase 4 if rotary knob or Markdown components prove difficult to style with utilities.

---

## Claude Model for Generation

| Option | Description | Selected |
|--------|-------------|----------|
| claude-sonnet-4-6 | Latest Sonnet 4.x. Strong citation grounding, 1–2s streaming latency, cost-efficient. Escalate to Opus if Phase 5 eval shows violations. | ✓ |
| claude-opus-4-7 | Highest reasoning quality, most reliable [Sn] inline enforcement. Slower and ~2–3× more expensive. | |

**User's choice:** claude-sonnet-4-6 (latest Sonnet 4.x)
**Notes:** Escalation path to claude-opus-4-7 deferred to Phase 5 eval decision.

---

## SSE Consumption in Next.js

| Option | Description | Selected |
|--------|-------------|----------|
| Fetch + ReadableStream | Custom hook. POST-compatible, parses custom events (event: citations), no new dependencies. | ✓ |
| Vercel AI SDK useChat | Handles streaming + history management. Adds external dependency; obscures custom event handling. | |

**User's choice:** Fetch + ReadableStream
**Notes:** EventSource eliminated at analysis stage (GET-only; /chat is POST). Vercel AI SDK explicitly out — same abstraction category as LangChain/LlamaIndex for this project.

---

## Citation Enforcement Strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Post-stream validation | After stream completes, parse response and strip out-of-range [Sn] refs before sending event: citations. Prevents drawer 404s. | ✓ |
| Prompt-only | Strong system prompt instructions only. Simpler but risks silent [Sn] fabrication — acceptable if occasional 404s are tolerable. | |

**User's choice:** Post-stream validation
**Follow-up — Citation timing:**

| Option | Description | Selected |
|--------|-------------|----------|
| Stream live, validate citations payload | Tokens flow immediately. After stream ends, strip invalid [Sn] from the citations payload. Text may show invalid ref but it won't be a clickable link. No latency impact. | ✓ |
| Buffer full response, then stream validated text | Hold all tokens until generation complete, validate, then emit corrected text. Adds full-generation wait before first token. | |

**User's choice:** Stream live, validate citations payload
**Notes:** Streaming UX preserved. Post-stream validation only affects the event: citations payload, not the token stream. Invalid [Sn] in text won't render as clickable pills (absent from citations payload).

---

## Claude's Discretion

- `app/generation/` module placement and submodule structure (`prompt.py`, `generator.py`)
- Exact `sse-starlette` 3.4.4 event format and `EventSourceResponse` constructor usage
- `frontend/` internal directory structure (standard App Router layout: `app/`, `components/`, `hooks/`)
- Coverage indicator wording for CITE-03 (e.g., "N sources agree")

## Deferred Ideas

- `DELETE /sessions/{session_id}` endpoint — frontend generates fresh UUID client-side on "New chat"
- CSS Modules — deferred to Phase 4 if needed for rotary knob/Markdown components
- `neighbor_chunks` in `/sources/{chunk_id}` response (ARCHITECTURE.md nice-to-have)
- Escalation to `claude-opus-4-7` pending Phase 5 eval results
