---
phase: 04-ui-polish-knobs-markdown-follow-ups
plan: "01"
subsystem: frontend
tags: [react-markdown, markdown-rendering, message-bubble, ui-polish]
dependency_graph:
  requires: []
  provides: [react-markdown-rendering, MARKDOWN_COMPONENTS, copy-to-clipboard]
  affects: [frontend/components/MessageBubble.tsx]
tech_stack:
  added: [react-markdown@10.1.0]
  patterns: [ReactMarkdown JSX mode, MARKDOWN_COMPONENTS const, group-hover copy button]
key_files:
  created: []
  modified:
    - frontend/components/MessageBubble.tsx
    - frontend/package.json
    - frontend/package-lock.json
decisions:
  - react-markdown v10.1.0 JSX mode satisfies T-03-14 (no dangerouslySetInnerHTML)
  - streamingClass moved to outer bubble wrapper div to prevent cursor inside react-markdown p/li
  - Copy button added per UI-SPEC §7 (full message text copy, group-hover reveal)
  - No rehype-raw or remark-gfm plugins (T-04-01 mitigation)
metrics:
  duration: "2 minutes"
  completed: "2026-05-22"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 3
---

# Phase 4 Plan 01: Markdown Rendering in MessageBubble Summary

react-markdown v10.1.0 installed and wired into MessageBubble.tsx with a MARKDOWN_COMPONENTS mapping covering 13 element types (p, strong, em, h1-h3, ul, ol, li, code, pre, blockquote, hr, a), replacing raw {message.content} text render in the assistant bubble with styled HTML output.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Install react-markdown and wire into MessageBubble | 5340dbe | frontend/package.json, frontend/package-lock.json, frontend/components/MessageBubble.tsx |

## What Was Built

**frontend/package.json:** Added `react-markdown@^10.1.0` to dependencies.

**frontend/components/MessageBubble.tsx:**
- Added `import ReactMarkdown from "react-markdown"` and `import type { Components } from "react-markdown"`
- Added `import { Copy, Check } from "lucide-react"` for copy button (pre-staged for Plan 3)
- Added `import { useState } from "react"` for copy button local state
- Declared `MARKDOWN_COMPONENTS: Components` const (module-level) mapping all 13 Markdown elements to their Tailwind classes per UI-SPEC §Typography table
- Replaced `{message.content}` raw text render with `<div className="space-y-1"><ReactMarkdown components={MARKDOWN_COMPONENTS}>{message.content}</ReactMarkdown></div>`
- Moved `streamingClass` (after:content-['▋'] after:animate-pulse after:text-zinc-400) from inner content to outer bubble wrapper div — cursor now on `max-w-[80%] bg-zinc-900` div, not inside any react-markdown-rendered element
- Added copy-to-clipboard button: ghost button, absolute top-right, group-hover reveal (opacity-0 → opacity-100), 2s success state with Check icon in green-500

## Verification Results

1. `grep -r "dangerouslySetInnerHTML" MessageBubble.tsx` → empty (PASS — T-04-02 satisfied)
2. `grep "import ReactMarkdown" MessageBubble.tsx` → import line found (PASS)
3. `grep "MARKDOWN_COMPONENTS" MessageBubble.tsx | wc -l` → 2 (PASS — definition + usage)
4. `npm run build` → exit 0 with Turbopack, TypeScript clean (PASS)
5. `grep '"react-markdown"' package.json` → `"react-markdown": "^10.1.0"` (PASS)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Node.js version mismatch caused native binding failure**
- **Found during:** Task 1, Step 5 (build verification)
- **Issue:** npm install ran under Node 19.6.0 (system default). Switching to Node 22 (required by Next.js 16.2.6) triggered `@tailwindcss/oxide` native binding failure: darwin-arm64 `.node` file was not present because it had been installed for a different platform/version combination.
- **Fix:** Removed node_modules and package-lock.json, reinstalled with Node 22.17.0 (via nvm). This regenerated the lock file and installed the correct darwin-arm64 native binary for `@tailwindcss/oxide`.
- **Files modified:** frontend/package-lock.json (regenerated)
- **Commit:** 5340dbe (included in same task commit)

## Known Stubs

None. The ReactMarkdown integration is fully wired. All 13 MARKDOWN_COMPONENTS entries render real output. The copy button uses navigator.clipboard.writeText with the full message.content string.

## Threat Flags

No new threat surface introduced beyond what is in the plan's threat model. react-markdown v10 JSX mode confirmed: no innerHTML, no rehype-raw, no raw HTML passthrough. T-04-01 and T-04-02 both mitigated as planned.

## Self-Check: PASSED

- frontend/components/MessageBubble.tsx exists: FOUND
- frontend/package.json contains react-markdown: FOUND
- Commit 5340dbe: FOUND
- npm run build exit 0: VERIFIED
