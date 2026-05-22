---
phase: 04-ui-polish-knobs-markdown-follow-ups
plan: "02"
subsystem: frontend
tags: [rotary-knob, svg, parseKnobs, message-bubble, post-stream-gate, ui-polish]
dependency_graph:
  requires: [04-01]
  provides: [parseKnobs-utility, RotaryKnob-component, knob-row-in-MessageBubble]
  affects: [frontend/components/MessageBubble.tsx]
tech_stack:
  added: []
  patterns: [inline-SVG-knob, regex-knob-parser, post-stream-gate-D08, last-value-wins-Map]
key_files:
  created:
    - frontend/utils/parseKnobs.ts
    - frontend/components/RotaryKnob.tsx
  modified:
    - frontend/components/MessageBubble.tsx
decisions:
  - matchAll() used over exec() loop to avoid stateful lastIndex on module-level g-flag regex
  - arcPath() helper extracted for SVG geometry to keep RotaryKnob component body readable
  - knobs computed inline (not useMemo) per UI-SPEC note — parseKnobs is a fast single regex pass
  - valueD set to null when safeValue===0 to avoid rendering a zero-length arc artifact
metrics:
  duration: "5 minutes"
  completed: "2026-05-22"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 3
---

# Phase 4 Plan 02: Rotary Knob Parser and SVG Component Summary

parseKnobs.ts pure utility (20-name regex, last-value-wins, 0-10 range filter) plus RotaryKnob.tsx inline SVG component (270° arc, zinc color scheme) wired into MessageBubble.tsx as a post-stream knob row behind the D-08 citations gate.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create parseKnobs.ts utility | aad987c | frontend/utils/parseKnobs.ts |
| 2 | Create RotaryKnob.tsx and wire knob row into MessageBubble | eaafbc3 | frontend/components/RotaryKnob.tsx, frontend/components/MessageBubble.tsx |

## What Was Built

**frontend/utils/parseKnobs.ts (new):**
- Exports `KnobValue` interface (`{ name: string; value: number }`) and `parseKnobs(text: string): KnobValue[]`
- `KNOB_RE` constant: 20 knob names (`Bass|Mid|Treble|Gain|Volume|Presence|Reverb|Tone|Drive|Level|Sustain|Output|Bright|High|Low|Delay|Mix|Rate|Depth|Feedback`), `gi` flags, `[=:]` separator, float-tolerant `(\d+(?:\.\d+)?)`
- `matchAll(KNOB_RE)` used instead of `exec()` loop — avoids mutating stateful `lastIndex` on module-level regex with `g` flag
- `Map<string, KnobValue>` keyed by lowercase name implements last-value-wins; Map preserves insertion order
- Out-of-range values (`< 0` or `> 10`) silently dropped — T-04-03 threat mitigation (adversarial model output)
- No external imports; pure TypeScript

**frontend/components/RotaryKnob.tsx (new):**
- Default export `RotaryKnob({ name, value }: RotaryKnobProps)`
- `arcPath()` helper: converts angleDeg to SVG coordinate via `(angleDeg - 90) * Math.PI / 180` formula (SVG 0° is 3 o'clock; subtract 90° to start from 12 o'clock)
- Track arc: `M startX startY A 30 30 0 1 1 endX endY` (largeArcFlag=1, 270° sweep)
- Value arc: sweep = `(safeValue/10)*270°`, `largeArcFlag = sweepAngle > 180 ? 1 : 0`; null when `safeValue === 0` to suppress zero-length arc artifact
- SVG `viewBox="0 0 80 88"` (80px circle area + 16px label zone at bottom)
- Colors: track `stroke-zinc-700`, value `stroke-zinc-300`, center dot `fill-zinc-400`, value text `fill-zinc-300`, name text `fill-zinc-500`
- `strokeLinecap="round"`, `strokeWidth={5}`, `fill="none"` on path elements
- `aria-label={name + ": " + displayValue}` for accessibility

**frontend/components/MessageBubble.tsx (modified):**
- Added `import { parseKnobs } from "@/utils/parseKnobs"` and `import RotaryKnob from "@/components/RotaryKnob"`
- `knobs` variable computed inline: `parseKnobs(message.content)` when `citations !== undefined && !isStreaming`, otherwise `[]`
- Knob row JSX inside the post-stream gate block, after `ReactMarkdown` content div and before `CoverageIndicator`
- Row markup: `<div className="flex flex-row flex-wrap gap-4 mt-3 pt-3 border-t border-zinc-800">` with mapped `<RotaryKnob key={k.name} ...>`
- `{/* Loading indicator — inserted by Plan 03 */}` comment placeholder preserved
- Final element order in bubble: (1) ReactMarkdown content, (2) loading indicator placeholder, (3) knob row, (4) CoverageIndicator, (5) citation pills

## Verification Results

1. `grep "import.*parseKnobs" MessageBubble.tsx` → `import { parseKnobs } from "@/utils/parseKnobs"` (PASS)
2. `grep "import RotaryKnob" MessageBubble.tsx` → `import RotaryKnob from "@/components/RotaryKnob"` (PASS)
3. `grep 'viewBox="0 0 80 88"' RotaryKnob.tsx` → matches (PASS)
4. `grep "stroke-zinc-700" RotaryKnob.tsx` → track path className (PASS)
5. `grep "stroke-zinc-300" RotaryKnob.tsx` → value path className (PASS)
6. `grep -c "parseKnobs" MessageBubble.tsx` → 3 (import + variable assignment + usage in JSX) (PASS)
7. `npm run build` → exit 0, TypeScript clean, Compiled successfully (PASS)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. The knob row is fully wired:
- `parseKnobs` regex is complete (20 knob names)
- `RotaryKnob` renders real SVG arcs with correct geometry
- Knob row renders from live `message.content` on completed messages

## Threat Flags

No new threat surface beyond the plan's threat model. T-04-03 (adversarial model output via parseKnobs) mitigated via range validation (values outside 0-10 silently dropped). T-04-04 (DoS via very long strings) accepted per plan — single-user local tool, bounded by model context window.

## Self-Check: PASSED

- frontend/utils/parseKnobs.ts exists: FOUND (created aad987c)
- frontend/components/RotaryKnob.tsx exists: FOUND (created eaafbc3)
- frontend/components/MessageBubble.tsx modified: FOUND (eaafbc3)
- Commit aad987c: FOUND
- Commit eaafbc3: FOUND
- npm run build exit 0: VERIFIED
