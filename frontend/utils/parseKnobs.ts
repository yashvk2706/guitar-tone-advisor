// parseKnobs — pure TypeScript utility, no external dependencies
// Parses knob name=value or name:value patterns from model-generated text.
// Used in MessageBubble.tsx after the post-stream gate (D-08) fires.

export interface KnobValue {
  /** Knob name as matched (e.g. "Bass", "Mid", "Treble") */
  name: string;
  /** Numeric value in the range [0, 10] (inclusive) */
  value: number;
}

/**
 * Regex matching the 20 supported knob names followed by `=` or `:` and a numeric value.
 *
 * Flags:
 *   g — global (all occurrences)
 *   i — case-insensitive (bass=7, BASS=7, Bass=7 all match)
 *
 * IMPORTANT: This regex has the `g` flag. Module-level regexes with `g` are stateful
 * (`lastIndex` persists between calls). We always use `String.prototype.matchAll(KNOB_RE)`
 * which creates a fresh iterator per call and does not mutate `KNOB_RE.lastIndex`.
 */
const KNOB_RE =
  /\b(Bass|Mid|Treble|Gain|Volume|Presence|Reverb|Tone|Drive|Level|Sustain|Output|Bright|High|Low|Delay|Mix|Rate|Depth|Feedback)\s*[=:]\s*(\d+(?:\.\d+)?)/gi;

/**
 * Parse knob name/value pairs from a completed (post-stream) assistant message.
 *
 * Behavior:
 * - Case-insensitive match on all 20 supported knob names.
 * - Both `=` and `:` separators accepted.
 * - Last-value-wins for duplicate knob names (e.g. "Bass=7 bass=3" → Bass:3).
 * - Only values in the range [0, 10] (inclusive) are returned; out-of-range values
 *   are silently dropped (T-04-03 threat mitigation — adversarial model output).
 * - Returns `[]` for empty input or input with no matching patterns.
 *
 * @param text The completed message content string.
 * @returns Array of KnobValue objects in last-seen key insertion order.
 */
export function parseKnobs(text: string): KnobValue[] {
  // Map keyed by lowercase name — implements last-value-wins semantics.
  // Map preserves insertion order; we update in place so the final name/value
  // for each key reflects the last match seen.
  const seen = new Map<string, KnobValue>();

  for (const match of text.matchAll(KNOB_RE)) {
    const name = match[1]; // capitalized as matched by the alternation
    const raw = match[2];
    const parsed = parseFloat(raw);

    // Range validation — silently drop out-of-range values (T-04-03).
    if (parsed < 0 || parsed > 10) continue;

    const key = name.toLowerCase();
    // Overwrite existing entry (last-value-wins) preserving last-seen casing.
    seen.set(key, { name, value: parsed });
  }

  return Array.from(seen.values());
}
