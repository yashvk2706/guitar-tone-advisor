---
status: partial
phase: 04-ui-polish-knobs-markdown-follow-ups
source: [04-VERIFICATION.md]
started: 2026-05-22T19:40:00Z
updated: 2026-05-22T19:40:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Loading state transitions (UI-04)
expected: "Searching corpus..." label appears from submit until first token; transitions to "Drafting..." on first token; both disappear when onDone fires
result: [pending]

### 2. Rotary knob visual rendering (UI-05)
expected: When model emits "Bass=7 Mid=4", SVG knobs appear under the completed message with arcs positioned at correct degree angles (not just empty SVGs)
result: [pending]

### 3. Copy button clipboard write (UI-03)
expected: Clicking copy button writes raw Markdown text to system clipboard; icon swaps to checkmark for 2 seconds, then reverts
result: [pending]

### 4. Follow-up rail click flow (CHAT-04)
expected: Clicking "Cleaner?" (or any button) dismisses the rail, posts that text as a new user turn, and starts a new streaming assistant response end-to-end
result: [pending]

### 5. Session history scroll (UI-02)
expected: With 5+ turns, prior messages remain fully visible and scrollable above the input; new messages auto-scroll into view
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
