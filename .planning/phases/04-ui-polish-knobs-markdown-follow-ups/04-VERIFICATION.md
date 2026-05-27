---
phase: 04-ui-polish-knobs-markdown-follow-ups
verified: 2026-05-22T12:00:00Z
status: complete
score: 14/14
overrides_applied: 0
human_verification:
  - test: "Open the web app, send a message with gear + tone target, wait for streaming response, observe the loading indicator"
    expected: "The assistant bubble shows 'Searching corpus...' immediately on submit, then transitions to 'Drafting...' when the first token arrives. The indicator disappears after streaming completes."
    why_human: "SSE streaming state-machine transitions depend on live backend; cannot verify idle→searching→drafting→idle timing programmatically without a running server."
  - test: "Send a message that elicits knob settings (e.g. 'What EQ settings for a blues tone on a Fender Deluxe?'). Wait for the response to complete."
    expected: "One or more rotary SVG knobs appear below the Markdown content — each showing the correct arc position and numeric label beneath the arc."
    why_human: "Rendering correctness of SVG knob positions requires visual inspection; automated checks can verify the component exists and SVG markup is present but cannot confirm visual arc accuracy."
  - test: "In the completed assistant response, hover over the message bubble. Click the Copy button (top-right corner)."
    expected: "The Copy icon becomes a green Check for ~2 seconds. Pasting into a text editor reveals the raw Markdown text of the recommendation."
    why_human: "Clipboard write and icon swap require browser interaction; navigator.clipboard is not available in node-based tests."
  - test: "Observe the three follow-up buttons ('Cleaner?', 'Live setting?', 'Budget version?') under the latest completed assistant message. Click one."
    expected: "The buttons disappear immediately and a new user message with the button's text appears in the chat, followed by a new streaming assistant response."
    why_human: "End-to-end follow-up click → submit → new stream requires live browser interaction and a running backend."
  - test: "Exchange multiple turns (3+) then scroll up in the message list."
    expected: "All prior turns remain visible and scrollable; the message list does not clip older messages."
    why_human: "Scroll behavior and visual rendering of session history requires browser verification."
---

# Phase 4: UI Polish — Knobs, Markdown, Follow-ups Verification Report

**Phase Goal:** The chat UI graduates from minimal-but-functional to actually-pleasant: Markdown formatting, visual rotary-knob renderings of knob settings, scrollable session history, one-click copy of the recommendation block, loading-state messaging, and three suggested follow-up action buttons under every answer.
**Verified:** 2026-05-22T12:00:00Z
**Status:** complete
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Markdown in assistant responses renders as styled HTML (bold, lists, code blocks, blockquotes) — not raw asterisks or backticks | VERIFIED | `ReactMarkdown` imported and used in `MessageBubble.tsx` line 179 with `MARKDOWN_COMPONENTS` covering all 13 element types (p, strong, em, h1-h3, ul, ol, li, code, pre, blockquote, hr, a). Build passes clean. |
| 2 | Streaming cursor (▋) appears on the outer bubble wrapper, not inside a react-markdown-rendered element | VERIFIED | `streamingClass` applied to the outer `max-w-[80%] bg-zinc-900` div (line 161) — not to the `<div className="space-y-1">` ReactMarkdown wrapper. |
| 3 | No dangerouslySetInnerHTML in any component (T-03-14 invariant) | VERIFIED | `grep` returns 0 occurrences across all files in `frontend/components/`. |
| 4 | `npm run build` exits 0 with TypeScript clean | VERIFIED | Build output: "Compiled successfully in 1105ms / Finished TypeScript in 948ms" — exit 0. (Requires Node 22 via nvm; Node 19 is insufficient.) |
| 5 | `parseKnobs('Bass=7 Mid=4 Treble=6')` returns `[{name:'Bass',value:7}, ...]` — correct regex, last-value-wins, range-filtered | VERIFIED | `KNOB_RE` regex at line 24 of `parseKnobs.ts` contains all 20 knob names, `gi` flags, `[=:]` separator. `matchAll()` used (safe re-entrancy). `Map<string, KnobValue>` keyed by lowercase implements last-value-wins. Values outside `[0,10]` dropped via `if (parsed < 0 \|\| parsed > 10) continue`. |
| 6 | `RotaryKnob` renders an inline SVG with `viewBox="0 0 80 88"`, 270° track arc, value arc, value label, name label | VERIFIED | `RotaryKnob.tsx`: `viewBox="0 0 80 88"` (line 74), `arcPath()` helper with `(angleDeg - 90) * Math.PI / 180` formula, `TRACK_START_DEG = -135`, 270° total sweep, `largeArcFlag=1` for track, `stroke-zinc-700` track / `stroke-zinc-300` value arc / `fill-zinc-400` center dot / `fill-zinc-300` value text / `fill-zinc-500` name text. |
| 7 | Knob row in `MessageBubble` only renders after `message.citations !== undefined && !message.isStreaming` (D-08 post-stream gate) | VERIFIED | `knobs` computed at line 142-145: `message.citations !== undefined && !message.isStreaming ? parseKnobs(message.content) : []`. Knob row JSX inside the same post-stream gate block (line 196). |
| 8 | While streaming, the assistant bubble shows 'Searching corpus...' then 'Drafting...' after first token; indicator disappears on completion | VERIFIED (code) | `streamPhase` state machine in `ChatPage.tsx`: `searching` set before `streamChat()` call (line 92), `drafting` on first token via `hasFirstTokenRef` (line 121), `idle` on error (line 152) and `setTimeout 300ms` on done (line 165). `loadingLabel` passed per-message in `messages.map()` (lines 238-240). `MessageBubble` renders `{message.isStreaming && loadingLabel && <p ...>{loadingLabel}</p>}` (line 185). — requires human verification of live state transitions. |
| 9 | Each assistant bubble has a copy button (top-right, opacity-0 group-hover:opacity-100) that copies raw Markdown to clipboard and shows a checkmark for 2 seconds | VERIFIED (code) | `relative group` on outer div (line 161). Copy button: `absolute top-2 right-2 opacity-0 group-hover:opacity-100` (line 166). `handleCopy` calls `navigator.clipboard.writeText(message.content)` (line 152). `setCopied(true)` + `setTimeout(() => setCopied(false), 2000)` (lines 154-155). `<Check size={14} className="text-green-500" />` when copied (line 171). — requires human verification of clipboard behavior. |
| 10 | Three follow-up buttons ('Cleaner?', 'Live setting?', 'Budget version?') appear under each completed answer | VERIFIED | `FollowUpRail.tsx`: `FOLLOW_UP_LABELS = ['Cleaner?', 'Live setting?', 'Budget version?'] as const` (line 4). Three `<button type="button">` elements with correct classNames per UI-SPEC §6. |
| 11 | Clicking a follow-up button submits that button's text as a new user turn | VERIFIED (code) | Data-flow chain: `FollowUpRail.onSubmit(label)` → `MessageBubble.onFollowUp(text)` → `ChatPage: onFollowUp={(text) => handleSubmit(text)}` (line 248) → `handleSubmit(overrideMessage)` uses `overrideMessage` over `inputValue` (line 79). |
| 12 | The follow-up rail does NOT appear during streaming (gated on `!message.isStreaming && citations !== undefined`) | VERIFIED | `FollowUpRail` render condition (line 191): `isLatestAssistant && message.citations !== undefined && !message.isStreaming && onFollowUp`. All four guards present. |
| 13 | The follow-up rail does NOT appear on messages other than the latest assistant message | VERIFIED | `isLatestAssistant` computed via `reduce` in `ChatPage` (line 233-235): `msg.role === 'assistant' ? idx : last` — only the last assistant index gets `true`. Passed per-message at line 247. |
| 14 | Full session history is visible and scrollable | VERIFIED | `ChatPage.tsx` `<main>` has `className="flex-1 overflow-y-auto ..."` (line 217). All messages render via `messages.map()` with no truncation. Auto-scroll behavior implemented via `scrollToBottom` callback and `messagesEndRef`. |

**Score:** 14/14 truths verified (5 require human browser testing for live confirmation)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/package.json` | react-markdown@10.1.0 dependency | VERIFIED | `"react-markdown": "^10.1.0"` present |
| `frontend/components/MessageBubble.tsx` | ReactMarkdown render, MARKDOWN_COMPONENTS, copy button, loadingLabel, knob row, FollowUpRail | VERIFIED | All features wired, 224 lines, substantive implementation |
| `frontend/utils/parseKnobs.ts` | parseKnobs() + KnobValue export | VERIFIED | 61 lines, pure TS, exports `KnobValue` interface and `parseKnobs` function |
| `frontend/components/RotaryKnob.tsx` | SVG rotary knob component, 0-10 scale | VERIFIED | 128 lines, `arcPath()` helper, correct SVG geometry per UI-SPEC §3 |
| `frontend/components/ChatPage.tsx` | streamPhase state machine, overrideMessage, isLatestAssistant | VERIFIED | All features present and wired, 293 lines |
| `frontend/components/FollowUpRail.tsx` | Three follow-up buttons with correct labels | VERIFIED | 26 lines, `FOLLOW_UP_LABELS` const, `type="button"` on each button |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `MessageBubble.tsx` | `react-markdown` | `import ReactMarkdown from 'react-markdown'` | WIRED | Line 4 — imported and used at line 179 |
| `MessageBubble` assistant branch | `MARKDOWN_COMPONENTS` | `<ReactMarkdown components={MARKDOWN_COMPONENTS}>` | WIRED | Line 31 (definition) + line 179 (usage inside `<div className="space-y-1">`) |
| `MessageBubble.tsx` | `parseKnobs.ts` | `import { parseKnobs } from '@/utils/parseKnobs'` | WIRED | Line 10 (import) + line 144 (usage) |
| `MessageBubble.tsx` | `RotaryKnob.tsx` | `import RotaryKnob from '@/components/RotaryKnob'` | WIRED | Line 11 (import) + line 202 (JSX usage in knob map) |
| `MessageBubble.tsx` | `FollowUpRail.tsx` | `import FollowUpRail from '@/components/FollowUpRail'` | WIRED | Line 12 (import) + line 192 (conditional render) |
| `ChatPage.tsx streamPhase` | `MessageBubble loadingLabel prop` | `loadingLabel` prop passed to streaming message | WIRED | Lines 238-240 (computed) + line 246 (passed) |
| `MessageBubble copy button` | `navigator.clipboard.writeText` | `handleCopy` calls clipboard API | WIRED | Lines 151-156 |
| `ChatPage.tsx messages.map()` | `MessageBubble isLatestAssistant prop` | reduce + `msg.role === 'assistant' && index === lastAssistantIndex` | WIRED | Lines 233-235 + 247 |
| `MessageBubble onFollowUp prop` | `FollowUpRail onSubmit prop` | `<FollowUpRail onSubmit={onFollowUp} />` | WIRED | Line 192 |
| `FollowUpRail onSubmit` | `ChatPage handleSubmit(overrideMessage)` | `onFollowUp={(text) => handleSubmit(text)}` | WIRED | Line 248 — `overrideMessage` path in `handleSubmit` at line 79 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `MessageBubble` loading label | `loadingLabel` prop | `ChatPage.streamPhase` state, driven by SSE callbacks (`onToken`, `onDone`, `onError`) | Yes — live SSE event-driven transitions | FLOWING |
| `MessageBubble` knob row | `knobs` (from `parseKnobs(message.content)`) | Live `message.content` accumulated token by token from SSE stream | Yes — parses real model output post-stream | FLOWING |
| `MessageBubble` copy button | `message.content` | Same SSE-accumulated content string | Yes — copies actual model response text | FLOWING |
| `FollowUpRail` | `FOLLOW_UP_LABELS` (compile-time const) | Fixed constant — not dynamic | N/A — intentionally static labels per spec | FLOWING |
| `RotaryKnob` | `name`, `value` from `KnobValue[]` | `parseKnobs(message.content)` on completed message | Yes — derives from live model output | FLOWING |

### Behavioral Spot-Checks

Step 7b skipped: requires running server (FastAPI + SSE streaming). The frontend build compiles cleanly but SSE-driven behaviors (streaming, citations, state transitions) cannot be spot-checked without a live backend. Routed to human verification.

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| npm build passes | `npm run build` (Node 22) | "Compiled successfully in 1105ms" — exit 0 | PASS |
| parseKnobs exports present | File read: `parseKnobs.ts` | `export interface KnobValue`, `export function parseKnobs` both present | PASS |
| FollowUpRail labels correct | `grep "Cleaner\|Live setting\|Budget version" FollowUpRail.tsx` | All three labels on line 4 as `as const` | PASS |
| All commits exist | `git log --oneline` | 5340dbe, aad987c, eaafbc3, 18cfab1, aab16a5, 526005e, 6ec5e76 all present | PASS |
| No dangerouslySetInnerHTML | `grep -c "dangerouslySetInnerHTML" MessageBubble.tsx` | 0 occurrences | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| UI-01 | 04-01-PLAN.md | Chat responses render Markdown (bold, lists, code blocks) correctly | SATISFIED | `MARKDOWN_COMPONENTS` maps 13 HTML elements to Tailwind classes; `ReactMarkdown` used in assistant bubble |
| UI-02 | 04-01-PLAN.md, 04-03-PLAN.md | Full session history visible and scrollable | SATISFIED | `ChatPage <main>` has `flex-1 overflow-y-auto`; all turns rendered in `messages.map()` |
| UI-03 | 04-03-PLAN.md | Copy recommendation block to clipboard with one click | SATISFIED | Copy button with `navigator.clipboard.writeText(message.content)`, 2s Check feedback |
| UI-04 | 04-03-PLAN.md | Loading/progress indicator shows state transitions | SATISFIED | `streamPhase` state machine (idle→searching→drafting→idle) wired to SSE callbacks; `loadingLabel` prop renders "Searching corpus..." / "Drafting..." |
| UI-05 | 04-02-PLAN.md | Rotary knob components for amp/pedal settings | SATISFIED | `RotaryKnob.tsx` inline SVG + `parseKnobs.ts` regex extractor wired in `MessageBubble` behind D-08 post-stream gate |
| CHAT-04 | 04-04-PLAN.md | Three follow-up action buttons under each answer | SATISFIED | `FollowUpRail.tsx` with 'Cleaner?', 'Live setting?', 'Budget version?' wired through `isLatestAssistant` gate; click path confirmed to `handleSubmit(overrideMessage)` |

All 6 phase requirements (CHAT-04, UI-01, UI-02, UI-03, UI-04, UI-05) have implementation evidence. No orphaned requirements found.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `ChatPage.tsx` | 267-268 | `placeholder=` attribute on textarea | Info | HTML input placeholder — not a code debt marker. No impact. |
| `MessageBubble.tsx` | 190 | Comment: `{/* FollowUpRail — appears under latest completed assistant message */}` | Info | Informational comment documenting position per UI-SPEC. Not a stub. |

No `TBD`, `FIXME`, or `XXX` markers found in any Phase 4 modified file. No empty stub implementations (`return null`, `return {}`, `return []`) found in production render paths.

**Notable structural deviation (informational — not a gap):** The plan specified `FollowUpRail` should render inside the outer assistant bubble div, after citation pills. The actual implementation places `FollowUpRail` outside the outer bubble div but before the post-stream gate block. The gating logic is functionally equivalent (`isLatestAssistant && message.citations !== undefined && !message.isStreaming && onFollowUp`). Visual ordering: FollowUpRail appears between the message bubble and the knob row / coverage / citation row — which may produce slightly different visual spacing than the plan intended but is not a functional regression.

### Human Verification Required

#### 1. Loading State Transitions (UI-04)

**Test:** Open the app (FastAPI + Next.js running). Type a message about gear + tone and submit.
**Expected:** The assistant bubble immediately shows "Searching corpus..." in small grey pulsing text. When the first token arrives (model starts typing), the label changes to "Drafting...". After the stream finishes and the citation event fires, the label disappears.
**Why human:** SSE streaming transitions (`onToken` first-call, `onDone`) require a live server. The state machine is verified in code but the timing cannot be confirmed without a running backend.

#### 2. Rotary Knob Visual Rendering (UI-05)

**Test:** Send a message that yields EQ/settings recommendations (e.g. "Blues tone on a Marshall JCM800"). After the response completes, observe the area below the Markdown content.
**Expected:** Visual rotary knob SVGs appear in a horizontal row. Each knob's arc sweeps clockwise from the 7-o'clock position to the correct degree for the value (e.g. Bass=7 should show roughly 190° of arc filled). The numeric value appears inside the arc and the knob name appears beneath.
**Why human:** Arc rendering accuracy and visual correctness requires visual inspection; the SVG markup existence is verified but geometric correctness can only be confirmed visually.

#### 3. Copy Button Behavior (UI-03)

**Test:** Hover over a completed assistant message bubble. Click the Copy icon (top-right corner).
**Expected:** The Copy icon swaps to a green checkmark for approximately 2 seconds, then reverts. Pasting in a text editor produces the raw Markdown text of the recommendation (including `**bold**`, `- list items`, `[S1]` citation markers).
**Why human:** `navigator.clipboard.writeText` requires a browser context with clipboard permissions; cannot be tested in Node.

#### 4. Follow-Up Rail Click Flow (CHAT-04)

**Test:** After a completed assistant response, three pill buttons should appear beneath the message: "Cleaner?", "Live setting?", "Budget version?". Click "Cleaner?".
**Expected:** The three buttons disappear immediately. A new user message "Cleaner?" appears in the chat. A new streaming assistant response begins (loading indicator shows). The original message's follow-up rail does not reappear.
**Why human:** The click-to-stream flow requires live browser interaction; the code path is verified but end-to-end behavior requires human confirmation.

#### 5. Scrollable Session History (UI-02)

**Test:** Have a conversation with 5+ turns (user + assistant exchanges). After the conversation, manually scroll up.
**Expected:** All previous turns are visible and scrollable. The message list does not clip or hide older messages. Auto-scroll to the latest message occurs after each new turn.
**Why human:** Visual scroll behavior and auto-scroll correctness require browser rendering verification.

### Gaps Summary

No code-level gaps found. All 6 Phase 4 requirements have complete implementation evidence:
- All 5 new artifacts exist and are substantive (not stubs)
- All 10 key links between components are wired and data-flowing
- The npm build passes cleanly with TypeScript validation
- No debt markers or empty implementations

The 5 human verification items above are all about live browser/server behavior that cannot be confirmed programmatically. They are not code gaps — they are confirmations of correct runtime behavior.

---

_Verified: 2026-05-22T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
