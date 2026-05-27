// parseKnobs — pure TypeScript utility, no external dependencies
// Parses knob name=value or name:value patterns, and markdown table rows,
// from model-generated text. Handles single values and ranges (e.g. "3-4").

export interface KnobValue {
  /** Knob label, e.g. "Bass" */
  name: string;
  /** Numeric value used for arc position — midpoint of range, or exact value */
  value: number;
  /** Display string shown as the label, e.g. "7" or "3-4" */
  display: string;
}

const KNOB_NAMES =
  "Bass|Mid|Treble|Gain|Volume|Presence|Reverb|Tone|Drive|Level|Sustain|Output|Bright|High|Low|Delay|Mix|Rate|Depth|Feedback";

// Pattern 1: inline  Name=N  or  Name: N  (single value or range)
// e.g. "Bass=5", "Gain: 3-4", "Treble=3–4"
const INLINE_RE = new RegExp(
  `\\b(${KNOB_NAMES})\\s*[=:]\\s*([\\d.]+(?:\\s*[–\\-]\\s*[\\d.]+)?)`,
  "gi"
);

// Pattern 2: markdown table row  | Name stuff | N |  or  | Name stuff | 3-4 |
// Matches the first column containing a knob name (optionally preceded by words
// like "Master", optionally followed by "/Drive" etc.), and the second column.
// e.g. "| Gain/Drive | 3–4 |", "| Bass | 5 |", "| Master Volume | 6 |"
const TABLE_RE = new RegExp(
  `\\|\\s*((?:\\w+\\s+)*(?:${KNOB_NAMES})(?:[/\\s]\\w+)*)\\s*\\|\\s*([\\d.]+(?:\\s*[–\\-]\\s*[\\d.]+)?)\\s*\\|`,
  "gi"
);

/**
 * Parse a raw value string (single or range) into a numeric position and display label.
 * Returns null if the value is out of the [0, 10] range.
 */
function parseRawValue(raw: string): { value: number; display: string } | null {
  // Normalise separators: em-dash or spaced hyphen → plain hyphen
  const normalised = raw.replace(/\s*[–\-]\s*/, "-").trim();
  const parts = normalised.split("-");

  if (parts.length === 1) {
    const v = parseFloat(parts[0]);
    if (isNaN(v) || v < 0 || v > 10) return null;
    return { value: v, display: String(v % 1 === 0 ? Math.round(v) : v) };
  }

  if (parts.length === 2) {
    const lo = parseFloat(parts[0]);
    const hi = parseFloat(parts[1]);
    if (isNaN(lo) || isNaN(hi) || lo < 0 || hi > 10 || lo > hi) return null;
    const mid = (lo + hi) / 2;
    // Display as "lo-hi" using original integers (avoid float noise like 3.0-4.0)
    return {
      value: mid,
      display: `${Math.round(lo)}-${Math.round(hi)}`,
    };
  }

  return null;
}

/**
 * Parse knob name/value pairs from a completed (post-stream) assistant message.
 *
 * Matches two formats:
 *   - Inline:  Bass=5, Gain: 3-4, Treble=3–4
 *   - Table:   | Gain/Drive | 3–4 |, | Bass | 5 |
 *
 * Behavior:
 * - Case-insensitive match on all 20 supported knob names.
 * - Both `=` and `:` separators accepted for inline format.
 * - Ranges (3-4 or 3–4) → midpoint used for arc position, "3-4" shown as label.
 * - Last-value-wins for duplicate knob names.
 * - Only values/ranges fully within [0, 10] are returned.
 * - Returns `[]` for empty input or no matches.
 */
export function parseKnobs(text: string): KnobValue[] {
  const seen = new Map<string, KnobValue>();

  const process = (nameRaw: string, valueRaw: string) => {
    // Extract the canonical knob name — the regex captures the knob name at
    // the start of the cell even when followed by "/Drive" etc.
    const nameMatch = new RegExp(`\\b(${KNOB_NAMES})`, "i").exec(nameRaw);
    if (!nameMatch) return;
    const name = nameMatch[1];

    const parsed = parseRawValue(valueRaw.trim());
    if (!parsed) return;

    seen.set(name.toLowerCase(), { name, ...parsed });
  };

  for (const m of text.matchAll(INLINE_RE)) process(m[1], m[2]);
  for (const m of text.matchAll(TABLE_RE)) process(m[1], m[2]);

  return Array.from(seen.values());
}
