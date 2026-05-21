# Phase 4: UI Polish — Knobs, Markdown, Follow-ups - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-21
**Phase:** 4-UI-Polish-Knobs-Markdown-Follow-ups
**Areas discussed:** Markdown library, Loading phase transition, Knob extraction pattern, Follow-up button scope

---

## Markdown Library

| Option | Description | Selected |
|--------|-------------|----------|
| react-markdown v10.1.0 | JSX output (T-03-14 safe), handles code fences/nested lists/blockquotes, streaming-tolerant, React 19 compatible. ~34KB gzip + 10 transitive deps. | ✓ |
| Custom regex renderer | Zero new deps, but breaks on code fences and nested lists without writing a partial parser. Only viable if LLM output stays provably simple. | |

**User's choice:** react-markdown v10.1.0 (recommended option)
**Notes:** No additional constraints added. The project's "no wrapper" policy targets LLM/retrieval abstractions, not UI rendering libraries.

---

## Loading Phase Transition

| Option | Description | Selected |
|--------|-------------|----------|
| Pure frontend: transition on first SSE token | Wire a state machine in ChatPage.tsx only. No backend changes. Uses `onToken` callback as first-token signal. Zero risk to Phase 3 SSE event contract. | ✓ |
| Backend `event: status` frames | Semantically accurate phase transitions. Requires changes to main.py + generator.py + useSSEStream. Risk to stable SSE contract. | |

**User's choice:** Pure frontend (recommended option)
**Notes:** Retrieval is sub-200ms; precise phase timing has no material impact. Backend SSE contract stays untouched.

---

## Knob Extraction Pattern

| Option | Description | Selected |
|--------|-------------|----------|
| Flexible line-level scan | Regex matches `Key=N` or `Key: N` anywhere in completed message text. No system prompt changes. Matches current compact-list format Claude already outputs. | ✓ |
| Heading-gated scan + prompt change | Extract only from under a Markdown heading. Requires changing SYSTEM_PROMPT_TEXT (busts prompt cache) and fails silently if model omits heading. | |

**User's choice:** Flexible line-level scan (recommended option)
**Notes:** Current SYSTEM_PROMPT_TEXT already instructs compact `Bass=7 Mid=4 Treble=6` format with no heading — heading-gated approach would fail structurally.

---

## Follow-up Button Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Latest assistant message only | Clean affordance for current dialogue state. 1 conditional in MessageBubble. No clutter in scrolled history. | ✓ |
| Every assistant message | Always visible while scrolling, but creates false impression of per-message branching. Clutters long histories. | |

**User's choice:** Latest assistant message only (recommended option)
**Notes:** Follow-up buttons are an affordance for current dialogue state, not a per-message annotation. All 4 choices matched the research recommendations.

---

## Claude's Discretion

- Copy button placement: per-message on each assistant bubble (full message text) rather than recommendation-block isolation
- Exact Tailwind styling for rotary knob, follow-up buttons, and loading indicator (match existing zinc/blue palette)
- Whether to show knob labels as `Bass: 7` or just `7` beneath the SVG

## Deferred Ideas

- CSS Modules — Tailwind utilities sufficient; defer unless SVG knob animations prove unmanageable
- Dynamic model-suggested follow-ups — separate phase; Phase 4 uses three fixed prompts
- Per-message reply branching — out of scope; follow-up buttons act on current session context
- Recommendation-block isolation via heading parsing — deferred in favor of full-message copy
