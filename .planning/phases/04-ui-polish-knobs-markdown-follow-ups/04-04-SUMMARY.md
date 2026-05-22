---
phase: 04-ui-polish-knobs-markdown-follow-ups
plan: "04"
subsystem: frontend
tags: [follow-up-rail, message-bubble, chat-page, ui-polish, final-build]
dependency_graph:
  requires: [04-02, 04-03]
  provides: [FollowUpRail-component, isLatestAssistant-wired, onFollowUp-wired, phase4-build-verified]
  affects:
    - frontend/components/FollowUpRail.tsx
    - frontend/components/MessageBubble.tsx
    - frontend/components/ChatPage.tsx
tech_stack:
  added: []
  patterns: [follow-up-rail, lastAssistantIndex-reduce, onFollowUp-callback, isLatestAssistant-gate]
key_files:
  created:
    - frontend/components/FollowUpRail.tsx
  modified:
    - frontend/components/MessageBubble.tsx
    - frontend/components/ChatPage.tsx
decisions:
  - FollowUpRail render gated on isLatestAssistant && citations !== undefined && !isStreaming && onFollowUp — four-way guard ensures rail only appears on latest completed assistant message and only when callback is wired
  - lastAssistantIndex computed via reduce before messages.map() — O(n) scan wrapped in IIFE to keep it co-located with the map without polluting component scope
  - onFollowUp prop guard in MessageBubble kept even though ChatPage always passes it — makes FollowUpRail safe when MessageBubble is used standalone (e.g., future tests)
  - FOLLOW_UP_LABELS declared as module-level const with as const — compile-time fixed strings satisfy T-04-07 (no user-controlled injection)
metrics:
  duration: "2 minutes"
  completed: "2026-05-22"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 2
---

# Phase 4 Plan 04: FollowUpRail Component and Final Phase Build Summary

FollowUpRail.tsx created with three compile-time fixed follow-up buttons ("Cleaner?", "Live setting?", "Budget version?"); wired into MessageBubble under the post-stream gate; ChatPage computes lastAssistantIndex via reduce and passes isLatestAssistant + onFollowUp to each bubble; npm run build exits 0 — Phase 4 complete.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create FollowUpRail.tsx component | 526005e | frontend/components/FollowUpRail.tsx |
| 2 | Wire FollowUpRail into MessageBubble and ChatPage; final build check | 6ec5e76 | frontend/components/MessageBubble.tsx, frontend/components/ChatPage.tsx |

## What Was Built

**frontend/components/FollowUpRail.tsx (new):**
- `const FOLLOW_UP_LABELS = ['Cleaner?', 'Live setting?', 'Budget version?'] as const`
- Props: `interface FollowUpRailProps { onSubmit: (text: string) => void; }`
- Default export: `function FollowUpRail({ onSubmit })`
- Three `<button type="button">` elements mapped from FOLLOW_UP_LABELS
- Button className per UI-SPEC §6: `h-7 px-3 rounded-full text-xs font-semibold bg-zinc-800 text-zinc-400 border border-zinc-700 hover:bg-zinc-700 hover:text-zinc-50 hover:border-zinc-600 transition-colors focus:outline-none focus:ring-1 focus:ring-blue-500 focus:ring-offset-1 focus:ring-offset-zinc-950`
- No state, no external imports

**frontend/components/MessageBubble.tsx:**
- Added `import FollowUpRail from '@/components/FollowUpRail'`
- Removed `_` prefix from `isLatestAssistant` and `onFollowUp` in function destructuring (props were forward-declared in Plan 03)
- Replaced `{/* FollowUpRail — Plan 04 inserts here */}` placeholder with:
  ```tsx
  {isLatestAssistant && message.citations !== undefined && !message.isStreaming && onFollowUp && (
    <FollowUpRail onSubmit={onFollowUp} />
  )}
  ```

**frontend/components/ChatPage.tsx:**
- messages.map() refactored into an IIFE to co-locate `lastAssistantIndex` reduce with the map
- `lastAssistantIndex` computed via `messages.reduce((last, msg, idx) => (msg.role === 'assistant' ? idx : last), -1)`
- map callback now receives `(msg, index)` parameter
- Each `<MessageBubble>` receives:
  - `isLatestAssistant={msg.role === 'assistant' && index === lastAssistantIndex}`
  - `onFollowUp={(text) => handleSubmit(text)}`

## Follow-Up Click Flow (verified correct)

1. User clicks "Cleaner?" button in FollowUpRail
2. `FollowUpRail.onSubmit("Cleaner?")` fires
3. `MessageBubble.onFollowUp("Cleaner?")` fires
4. `ChatPage.handleSubmit("Cleaner?")` called with `overrideMessage = "Cleaner?"`
5. `message = "Cleaner?"` (overrideMessage wins); guard passes (truthy, not streaming)
6. Textarea NOT cleared (overrideMessage !== undefined branch)
7. User message `{ role: "user", content: "Cleaner?" }` appended to messages
8. New streaming assistant message appended
9. `streamChat("Cleaner?", ...)` called
10. FollowUpRail disappears: new latest assistant message has `isStreaming=true`, suppressing the gate

## Verification Results

1. `grep "FollowUpRail" MessageBubble.tsx | wc -l` → 3 (import, import path, render) — PASS (>= 2)
2. `grep "isLatestAssistant" ChatPage.tsx` → prop line + lastAssistantIndex comparison — PASS (>= 2 occurrences total)
3. `grep "lastAssistantIndex" ChatPage.tsx` → reduce line + prop pass — PASS
4. `grep -r "dangerouslySetInnerHTML" frontend/components/` → empty (exit 1) — PASS (T-03-14 invariant satisfied)
5. `grep "react-markdown" frontend/package.json` → `"react-markdown": "^10.1.0"` — PASS
6. `grep "streamPhase" ChatPage.tsx | wc -l` → >= 5 — PASS
7. `grep "navigator.clipboard" MessageBubble.tsx` → handleCopy line — PASS
8. `npm run build` → exit 0, TypeScript clean — PASS (Phase 4 final build check)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. All features fully wired:
- FollowUpRail renders three buttons with fixed compile-time labels
- isLatestAssistant computed from live messages array on every render
- onFollowUp calls handleSubmit(text) which triggers full SSE stream
- Follow-up submission clears the rail immediately (new streaming message suppresses gate)

## Threat Flags

No new threat surface beyond the plan's threat model:
- T-04-07 (follow-up label spoofing): accepted — FOLLOW_UP_LABELS are compile-time constants; no user-controlled input reaches onSubmit
- T-04-08 (handleSubmit overrideMessage): accepted — overrideMessage only comes from FollowUpRail fixed labels; single-user local tool

## Self-Check: PASSED

- frontend/components/FollowUpRail.tsx created: FOUND (commit 526005e)
- frontend/components/MessageBubble.tsx modified: FOUND (commit 6ec5e76)
- frontend/components/ChatPage.tsx modified: FOUND (commit 6ec5e76)
- "Cleaner?" in FollowUpRail.tsx: FOUND
- "Live setting?" in FollowUpRail.tsx: FOUND
- "Budget version?" in FollowUpRail.tsx: FOUND
- FollowUpRail import in MessageBubble.tsx: FOUND
- FollowUpRail render with 4-way gate in MessageBubble.tsx: FOUND
- lastAssistantIndex reduce in ChatPage.tsx: FOUND
- isLatestAssistant prop in ChatPage.tsx: FOUND
- onFollowUp prop in ChatPage.tsx: FOUND
- npm run build exit 0: VERIFIED (Compiled successfully in 1066ms, TypeScript clean)
