// RotaryKnob — inline SVG rotary knob component (UI-SPEC §3)
// Renders a 270° arc knob on a 0–10 scale with name and value labels.
// No external SVG library — pure React + Tailwind + inline SVG.

interface RotaryKnobProps {
  /** Knob label, e.g. "Bass" */
  name: string;
  /** Current knob value, 0.0 – 10.0 — controls arc position */
  value: number;
  /** Display string for the label, e.g. "7" or "3-4". Defaults to value. */
  display?: string;
}

/**
 * Compute the SVG arc path string for a circular arc segment.
 *
 * The coordinate system maps standard angles to SVG space by subtracting 90°:
 *   - SVG 0° is at 3 o'clock (east)
 *   - Subtracting 90° moves the reference to 12 o'clock (north)
 *   - So angleDeg=0 → 12 o'clock; angleDeg=−135 → 7 o'clock; angleDeg=+135 → 5 o'clock
 *
 * @param cx        Circle center X
 * @param cy        Circle center Y
 * @param r         Circle radius
 * @param startDeg  Start angle in degrees (standard, 0=12 o'clock after −90° correction)
 * @param endDeg    End angle in degrees
 * @param large     Large arc flag (1 if sweep > 180°, 0 otherwise)
 * @returns SVG path d attribute string
 */
function arcPath(
  cx: number,
  cy: number,
  r: number,
  startDeg: number,
  endDeg: number,
  large: 0 | 1
): string {
  const toRad = (deg: number) => ((deg - 90) * Math.PI) / 180;
  const sx = cx + r * Math.cos(toRad(startDeg));
  const sy = cy + r * Math.sin(toRad(startDeg));
  const ex = cx + r * Math.cos(toRad(endDeg));
  const ey = cy + r * Math.sin(toRad(endDeg));
  // sweepFlag=1 → clockwise (matches the direction of knob travel)
  return `M ${sx.toFixed(3)} ${sy.toFixed(3)} A ${r} ${r} 0 ${large} 1 ${ex.toFixed(3)} ${ey.toFixed(3)}`;
}

export default function RotaryKnob({ name, value, display }: RotaryKnobProps) {
  // Clamp to valid range in case caller passes out-of-bounds value
  const safeValue = Math.max(0, Math.min(10, value));

  // Arc geometry constants
  const CX = 40;
  const CY = 40;
  const R = 30;
  const TRACK_START_DEG = -135; // 7 o'clock
  const TRACK_END_DEG = 135; // 5 o'clock
  // Total track sweep = 270°; largeArcFlag=1 because 270 > 180
  const trackD = arcPath(CX, CY, R, TRACK_START_DEG, TRACK_END_DEG, 1);

  // Value arc: sweep = (safeValue / 10) * 270°, starting from the same 7 o'clock position
  const sweepAngle = (safeValue / 10) * 270;
  const valueEndDeg = TRACK_START_DEG + sweepAngle;
  const valueLargeArc: 0 | 1 = sweepAngle > 180 ? 1 : 0;
  const valueD =
    safeValue > 0
      ? arcPath(CX, CY, R, TRACK_START_DEG, valueEndDeg, valueLargeArc)
      : null;

  // Display label: use explicit display prop if provided (e.g. "3-4" for ranges),
  // otherwise derive from value.
  const displayValue = display ?? (Number.isInteger(safeValue)
    ? String(safeValue)
    : safeValue.toFixed(1));

  return (
    <svg
      viewBox="0 0 80 88"
      width="80"
      height="88"
      aria-label={`${name}: ${displayValue}`}
    >
      {/* Track arc — full 270° background ring */}
      <path
        d={trackD}
        className="stroke-zinc-700"
        strokeWidth={5}
        strokeLinecap="round"
        fill="none"
      />

      {/* Value arc — filled portion from 7 o'clock to current position */}
      {valueD !== null && (
        <path
          d={valueD}
          className="stroke-zinc-300"
          strokeWidth={5}
          strokeLinecap="round"
          fill="none"
        />
      )}

      {/* Center indicator dot */}
      <circle cx="40" cy="40" r="3" className="fill-zinc-400" stroke="none" />

      {/* Numeric value label — centered inside the arc */}
      <text
        x="40"
        y="58"
        textAnchor="middle"
        fontSize="14"
        fontWeight="600"
        className="fill-zinc-300"
      >
        {displayValue}
      </text>

      {/* Knob name label — beneath the arc */}
      <text
        x="40"
        y="82"
        textAnchor="middle"
        fontSize="10"
        fontWeight="400"
        className="fill-zinc-500"
      >
        {name}
      </text>
    </svg>
  );
}
