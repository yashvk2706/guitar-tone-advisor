# Phase 4: UI Polish — Knobs, Markdown, Follow-ups - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Graduate the minimal Phase 3 chat UI to actually pleasant: Markdown rendering in assistant responses, visual rotary-knob renderings of amp/pedal settings parsed from model output, scrollable session history polish, one-click copy of the recommendation block, labeled loading-state transitions while the response generates, and three fixed follow-up suggestion buttons under the latest answer.

**In scope:** `frontend/components/MessageBubble.tsx` (Markdown rendering, follow-up rail, rotary knob display), `frontend/components/ChatPage.tsx` (loading-state machine, history scroll polish), a new `frontend/components/RotaryKnob.tsx` SVG component, a new `frontend/utils/parseKnobs.ts` parser, a new `frontend/components/FollowUpRail.tsx`, copy-to-clipboard handler on recommendation blocks.

**Out of scope:** Backend changes (no new SSE events needed — loading state is pure-frontend), hybrid tsvector+RRF retrieval (Phase 5), RAGAS eval (Phase 5), corpus expansion (later milestone), additional corpus source types.

</domain>

<decisions>
## Implementation Decisions

### Markdown Rendering
- **D-01:** Use **react-markdown v10.1.0** in `MessageBubble.tsx`. JSX output — never calls `innerHTML`, satisfies T-03-14 hard constraint. Handles code fences, nested lists, and blockquotes (all realistic in gear-recommendation responses). Streaming-safe: accepts a partial, growing string as `children` and re-renders incrementally on each token append without requiring a completed document. Change is isolated to `MessageBubble.tsx` — replace `{message.content}` raw text render with `<ReactMarkdown>{message.content}</ReactMarkdown>`. React 19.2.4 satisfies the React >=18 peer dependency.

### Loading State Machine
- **D-02:** Pure-frontend state machine in `ChatPage.tsx` only. No backend changes. State: `streamPhase: 'idle' | 'searching' | 'drafting' | 'done'`. Transitions: submit → `searching`; first `onToken` fires → `drafting`; `onDone` fires → `done` (resets to `idle` after display). The `onToken` callback in `streamChat()` is the first-token signal — use it to drive the `searching → drafting` transition. UI shows a labeled progress indicator near the assistant bubble: "Searching corpus..." in the `searching` phase, "Drafting..." in the `drafting` phase. The Phase 3 SSE event contract (`event: session` → tokens → `event: citations`) is unchanged.

### Rotary Knob Extraction Pattern
- **D-03:** Flexible line-level scan — regex matches `Key=N` or `Key: N` (case-insensitive, float-tolerant) anywhere in the **completed** (post-stream) message text. No system prompt changes. This matches the current `SYSTEM_PROMPT_TEXT` format which already instructs Claude to emit compact lists like `Bass=7 Mid=4 Treble=6`. Last-value-wins for duplicate knob names. The knob names to scan: Bass, Mid, Treble, Gain, Volume, Presence, Reverb, Tone, Drive, Level, Sustain, Output, Bright, High, Low, Delay, Mix, Rate, Depth, Feedback. Knob parsing runs client-side on the completed message only — not during streaming.
- **D-04:** Rotary knob SVG component (`RotaryKnob.tsx`) — inline SVG, 0–10 scale, value label beneath. No external SVG-knob library. Position maps linearly: 0 = 7 o'clock (−135°), 10 = 5 o'clock (+135°). Knobs render in a horizontal row below the Markdown-rendered message text, replacing (or supplementing) the inline `Key=N` compact list in the response. Rendered only after streaming completes (alongside citations).

### Follow-up Button Scope
- **D-05:** Follow-up rail (`FollowUpRail.tsx`) renders only under the **latest** assistant message. `MessageBubble` receives an `isLatestAssistant: boolean` prop — the rail is conditionally rendered when `isLatestAssistant && message.citations !== undefined && !message.isStreaming` (i.e., after the response completes and citations have fired). Three fixed button labels: **"Cleaner?"**, **"Live setting?"**, **"Budget version?"**. Clicking submits the button label text as a new user turn via the existing `handleSubmit` path in `ChatPage.tsx`. Buttons appear as a horizontal pill row below the citation pills.

### Claude's Discretion
- Copy button placement: either on a dedicated "recommendation block" identified by a heading, or as a per-message copy button on each assistant bubble. If isolating a recommendation section proves unreliable, fall back to copying the full message text.
- Exact Tailwind styling for the rotary knob, follow-up buttons, and loading indicator — match the existing zinc/blue palette.
- Whether to show knob labels as `Bass: 7` or just `7` beneath the SVG — implementation choice.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Scope
- `.planning/REQUIREMENTS.md` §UI (UI-01 through UI-05), §Chat & Conversation (CHAT-04) — all Phase 4 acceptance criteria
- `.planning/ROADMAP.md` §Phase 4 — 4 planned plans with descriptions, 6 success criteria, UI hint: yes

### Existing Frontend (MANDATORY — read before writing any component)
- `frontend/components/MessageBubble.tsx` — integration point for Markdown renderer (D-01), knob display (D-04), and follow-up rail (D-05); currently renders `{message.content}` as raw text
- `frontend/components/ChatPage.tsx` — integration point for loading state machine (D-02); currently has `isStreaming: boolean` state; `handleSubmit` is the submit path for follow-up button clicks
- `frontend/hooks/useSSEStream.ts` — `onToken` callback is the first-token signal for D-02; `onCitations` is the post-stream signal for when knobs and follow-up rail appear
- `frontend/components/CitationPill.tsx` and `frontend/components/CoverageIndicator.tsx` — established rendering patterns for post-stream elements (D-08 from Phase 3: nothing below the message appears until `event:citations` fires)

### Generation & System Prompt
- `app/generation/prompt.py` — `SYSTEM_PROMPT_TEXT`: the knob parser (D-03) must match the actual format Claude is instructed to use. The prompt instructs compact `Key=N` space-separated lists — heading-gated extraction would fail silently.

### Architecture & Phase 3 Decisions
- `.planning/phases/03-grounded-generation-minimal-chat-ui/03-CONTEXT.md` — D-01 (App Router + TypeScript + Tailwind), D-05 (Fetch + ReadableStream, no Vercel AI SDK), D-08 (no citation elements before `event:citations`), T-03-14 (no dangerouslySetInnerHTML)
- `.planning/research/ARCHITECTURE.md` §API Design — SSE event sequence (unchanged in Phase 4)

### Stack
- `.planning/research/STACK.md` §Recommended Stack Summary — pinned frontend versions (Next.js 16.2.6, React 19.2.4, Tailwind 4)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `frontend/components/MessageBubble.tsx:48–55` — the `streamingClass` Tailwind pattern for cursor and the `{message.content}` raw text render is exactly what gets replaced by `<ReactMarkdown>` in D-01
- `frontend/hooks/useSSEStream.ts` — `onToken` callback (fires on first data token) is the `searching → drafting` transition signal for D-02; `onCitations` (fires after `event:citations`) is the render gate for knobs and follow-up buttons (D-04, D-05)
- `frontend/components/ChatPage.tsx:94–153` — `handleSubmit` path accepts message string + sessionId — follow-up buttons can call it directly with a fixed string (D-05)
- `frontend/components/CitationPill.tsx` — `inline-flex items-center h-5 px-1.5 rounded text-xs` pattern for horizontal pill rows; follow-up buttons will use a similar pill style

### Established Patterns
- **T-03-14 (no dangerouslySetInnerHTML):** `react-markdown` satisfies this; all other rendering must also avoid it
- **Post-stream render gate (D-08):** citation pills and coverage indicator only appear after `message.citations !== undefined && !message.isStreaming`; knobs and follow-up rail follow the same gate
- **No external streaming during streaming:** knob parsing, recommendation block isolation, and follow-up rail all operate on completed messages only
- **`gear=null` pattern:** follow-up button clicks submit plain text with `gear=null` — same as Phase 3 regular turns

### Integration Points
- `MessageBubble.tsx` receives `Message` type — adding `isLatestAssistant: boolean` prop is the minimal change for D-05
- `ChatPage.tsx` state: add `streamPhase: 'idle' | 'searching' | 'drafting' | 'done'` alongside existing `isStreaming`; `isStreaming` can remain for the disabled-input logic

</code_context>

<specifics>
## Specific Ideas

- **Knob regex:** `/\b(Bass|Mid|Treble|Gain|Volume|Presence|Reverb|Tone|Drive|Level|Sustain|Output|Bright|High|Low|Delay|Mix|Rate|Depth|Feedback)\s*[=:]\s*(\d+(?:\.\d+)?)/gi` — last-value-wins for duplicates; only render knobs where parsed value is 0–10
- **Rotary SVG arc:** center at (50,50), radius 35, stroke-dasharray + stroke-dashoffset to draw an arc from 7 o'clock to the current position; value label at `<text y="75" textAnchor="middle">{label}: {value}</text>` beneath the circle
- **Loading indicator position:** inside the assistant message bubble, as a bottom-aligned status bar: `text-xs text-zinc-500 mt-1 animate-pulse "Searching corpus..."` → `"Drafting..."` — disappears when `onDone` fires
- **Copy button:** per-message on each assistant bubble (simpler than recommendation-block isolation); `navigator.clipboard.writeText(message.content)` — copies the raw Markdown text; show a checkmark for 2s after copy

</specifics>

<deferred>
## Deferred Ideas

- CSS Modules — Tailwind utilities are sufficient; defer unless SVG knob animations prove unmanageable
- Dynamic model-suggested follow-ups ("would you like to hear about...") — separate phase; Phase 4 uses three fixed prompts
- Per-message reply branching — out of scope; follow-up buttons act on current session context only
- Recommendation-block isolation via heading parsing — deferred in favor of full-message copy (simpler, no system prompt coupling)

</deferred>

---

*Phase: 4-UI-Polish-Knobs-Markdown-Follow-ups*
*Context gathered: 2026-05-21*
