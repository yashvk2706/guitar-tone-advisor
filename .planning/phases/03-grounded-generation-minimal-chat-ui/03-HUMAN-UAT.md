---
status: partial
phase: 03-grounded-generation-minimal-chat-ui
source: [03-VERIFICATION.md]
started: 2026-05-21T15:55:00Z
updated: 2026-05-21T15:55:00Z
---

## Current Test

[awaiting human confirmation]

## Tests

### 1. End-to-end streaming with citations
expected: Ask "What amp settings did BB King use?" — see streamed tokens, [Sn] pills appear only after stream ends, clicking pill shows [Forum] badge + chunk text in drawer
result: [pending]

### 2. Refusal behavior
expected: Query against topic with no corpus data produces "I don't have material on..." rather than fabricated settings
result: [pending]

### 3. Gear translation phrasing
expected: When user's gear differs from corpus gear, response maps settings to user's equivalent
result: [pending]

### 4. Concrete knob positions
expected: Corpus chunks with EQ data yield Bass=N Mid=N Treble=N formatted output
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
