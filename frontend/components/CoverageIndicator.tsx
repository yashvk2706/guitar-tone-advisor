// Coverage indicator: "● N sources agree" per UI-SPEC §6

interface CoverageIndicatorProps {
  count: number;
}

export default function CoverageIndicator({ count }: CoverageIndicatorProps) {
  // N=0: render nothing
  if (count === 0) return null;

  // N=1: "● 1 source" (singular — no "agree")
  // N>1: "● N sources agree"
  const text = count === 1 ? '1 source' : `${count} sources agree`;

  return (
    <div className="flex items-center gap-1.5 text-xs text-zinc-400 mt-1">
      <span className="h-2 w-2 rounded-full bg-green-500 shrink-0 inline-block" />
      <span>{text}</span>
    </div>
  );
}
