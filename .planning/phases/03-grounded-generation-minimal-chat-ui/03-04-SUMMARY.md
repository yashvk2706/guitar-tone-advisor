---
phase: 03-grounded-generation-minimal-chat-ui
plan: "04"
subsystem: ui
tags: [nextjs, react, typescript, tailwind, sse, lucide-react, streaming, citations]

# Dependency graph
requires:
  - phase: 03-grounded-generation-minimal-chat-ui
    plan: 03
    provides: "FastAPI SSE endpoint POST /chat, GET /sources/{chunk_id}, GET /health"

provides:
  - "frontend/ Next.js App Router with TypeScript + Tailwind + lucide-react"
  - "next.config.js /api/py/* → http://localhost:8000/* reverse proxy rewrite"
  - "useSSEStream.ts ReadableStream SSE parser with session/token/citations/error/done callbacks"
  - "ChatPage.tsx full orchestration component with streaming, session, and citation drawer state"
  - "MessageBubble.tsx user/assistant/error bubble variants with ▋ streaming cursor"
  - "CitationPill.tsx clickable [Sn] pills (blue, rendered only after event:citations fires)"
  - "CitationDrawer.tsx right-side overlay with source-type badge and raw chunk text"
  - "CoverageIndicator.tsx '● N sources agree' / '● 1 source' coverage label"

affects:
  - "04-ui-polish-knobs-markdown-follow-ups"

# Tech tracking
tech-stack:
  added:
    - "Next.js 16.2.6 (App Router, TypeScript)"
    - "Tailwind CSS 4 (via create-next-app)"
    - "lucide-react (SquarePen, X icons)"
  patterns:
    - "ReadableStream SSE parsing with /\\r?\\n\\r?\\n/ frame splitting and ':' comment skipping"
    - "Deferred citation rendering — event:citations fires after stream ends (D-08 rule)"
    - "Standalone streamChat() async function (not a React hook) called from event handlers"
    - "session_id: null on first turn, UUID from event:session fires callback"
    - "Gear sent as null from UI — user types gear description in plain text (Phase 3 pattern)"

key-files:
  created:
    - frontend/next.config.js
    - frontend/app/layout.tsx
    - frontend/app/page.tsx
    - frontend/hooks/useSSEStream.ts
    - frontend/components/ChatPage.tsx
    - frontend/components/MessageBubble.tsx
    - frontend/components/CitationPill.tsx
    - frontend/components/CitationDrawer.tsx
    - frontend/components/CoverageIndicator.tsx
  modified: []

key-decisions:
  - "SSE frame splitting uses /\\r?\\n\\r?\\n/ not \\n\\n — sse-starlette 3.4.4 emits \\r\\n separators (Pitfall 4)"
  - "Lines starting with ':' skipped to avoid sse-starlette ping comments corrupting JSON.parse (Pitfall 2)"
  - "Citation pills rendered only after event:citations fires — D-08 hard rule, not during streaming"
  - "New Chat resets sessionId client-side only — no backend API call (D-17)"
  - "gear=null sent on all turns in Phase 3 — user describes gear in plain text message"
  - "chunk_text rendered via JSX text content ({drawer.data.chunk_text}), never dangerouslySetInnerHTML — T-03-14 satisfied"
  - "CommonJS module.exports used for next.config.js (not ESM) — Next.js 15/16 config format compatibility"

patterns-established:
  - "streamChat(): standalone async function, not a React hook — called from ChatPage.tsx submit handler"
  - "SSE buffer accumulation: TextDecoder + chunk reader + leftover buffer pattern"
  - "Deferred citation state: message.citations stays undefined during streaming; set by onCitations callback"
  - "Source-type badge color map: forum=emerald, pdf_manual=amber, web_article=violet, youtube=rose"

requirements-completed:
  - CHAT-01
  - CHAT-03
  - CITE-01
  - CITE-02
  - CITE-03

# Metrics
duration: 60min
completed: 2026-05-20
---

# Phase 3 Plan 04: Next.js Chat UI Summary

**Next.js App Router chat frontend with ReadableStream SSE streaming, deferred citation pills ([Sn]), source-type drawer, and coverage indicator — completing the end-to-end guitar tone advisor flow.**

## Performance

- **Duration:** ~60 min
- **Started:** 2026-05-20T18:00:00Z
- **Completed:** 2026-05-20T18:40:00Z
- **Tasks:** 2 automated + 1 checkpoint (human-verify)
- **Files modified:** 9

## Accomplishments

- Next.js 16.2.6 App Router scaffold with TypeScript, Tailwind 4, lucide-react, and /api/py/* proxy rewrite to localhost:8000
- ReadableStream SSE parser (`useSSEStream.ts`) with /\r?\n\r?\n/ frame splitting, ':' ping-comment skipping, and session/token/citations/error/done callback dispatch
- Full chat UI: streaming assistant bubbles with ▋ cursor, deferred citation pills that appear only after event:citations fires, right-side citation drawer with source-type badges, coverage indicator, New Chat reset
- Human checkpoint passed — all 9 manual verification checks approved

## Task Commits

Each task was committed atomically:

1. **Task 1: Scaffold Next.js app and configure proxy rewrites** - `05b6ff3` (feat)
2. **Task 2: Chat components, SSE hook, and citation drawer** - `f82612e` (feat)

**Plan metadata:** (committed in this run — docs)

## Files Created/Modified

- `frontend/next.config.js` - CommonJS rewrite config: /api/py/:path* → http://localhost:8000/:path*
- `frontend/app/layout.tsx` - Root layout with bg-zinc-950 text-zinc-50, no Google Fonts
- `frontend/app/page.tsx` - Thin "use client" shell wrapping ChatPage
- `frontend/hooks/useSSEStream.ts` - streamChat() standalone async function; ReadableStream SSE parser; exports CitationSource type
- `frontend/components/ChatPage.tsx` - Full orchestration: sessionId, messages, isStreaming, drawer state; header with SquarePen New Chat button; auto-scroll; Enter-to-submit input
- `frontend/components/MessageBubble.tsx` - user/assistant/error variants; ▋ streaming cursor via after:content-['▋'] after:animate-pulse; citation pills only when message.citations is set
- `frontend/components/CitationPill.tsx` - Blue [Sn] pills with hover and focus ring styles per UI-SPEC §4
- `frontend/components/CitationDrawer.tsx` - Fixed right-side overlay; backdrop close; source-type badge color map (forum=emerald, manual=amber, article=violet, youtube=rose); skeleton loading; chunk text in monospace
- `frontend/components/CoverageIndicator.tsx` - Returns null for N=0; "● 1 source" for N=1; "● N sources agree" for N>1

## Decisions Made

- **SSE frame separator:** /\r?\n\r?\n/ — sse-starlette 3.4.4 emits CRLF separators; splitting on \n\n alone would fail to split frames correctly (Pitfall 4 from RESEARCH.md)
- **Ping comment skipping:** Lines starting with ":" are skipped before parsing — prevents JSON.parse errors from sse-starlette ping comments (Pitfall 2)
- **Deferred citation rendering:** Citation pills are absent from the DOM while isStreaming is true; they are only set on the message after event:citations fires. This is a hard D-08 requirement.
- **No dangerouslySetInnerHTML in CitationDrawer:** chunk_text is rendered as a JSX text node, which React escapes — satisfies T-03-14 (XSS mitigation)
- **New Chat is client-only:** setSessionId(null) + setMessages([]) + setDrawer(null); no backend API call per D-17

## Deviations from Plan

None — plan executed exactly as written. All 9 human verification checks passed.

## Issues Encountered

None. npm run build passed with no TypeScript errors on Node 22 / Next.js 16.2.6.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced beyond what was documented in the plan's threat model. T-03-14 (XSS via chunk_text) satisfied — React JSX text escaping confirmed; no dangerouslySetInnerHTML present.

## User Setup Required

None — no external service configuration required beyond what was already configured (Postgres + OpenAI API key in .env from prior phases).

## Next Phase Readiness

- Phase 3 complete. All 4/4 plans shipped.
- End-to-end flow verified: user types gear + tone → FastAPI retrieves → streams cited answer → citation drawer opens with source chunk text
- Phase 4 (UI Polish) can begin: Markdown rendering, rotary-knob components, follow-up buttons, copy-to-clipboard

---
*Phase: 03-grounded-generation-minimal-chat-ui*
*Completed: 2026-05-20*
