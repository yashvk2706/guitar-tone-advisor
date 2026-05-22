// Follow-up suggestion rail per UI-SPEC §6
// Three fixed prompt buttons appear under the latest completed assistant message.

const FOLLOW_UP_LABELS = ['Cleaner?', 'Live setting?', 'Budget version?'] as const;

interface FollowUpRailProps {
  onSubmit: (text: string) => void;
}

export default function FollowUpRail({ onSubmit }: FollowUpRailProps) {
  return (
    <div className="flex flex-row flex-wrap gap-2 mt-2">
      {FOLLOW_UP_LABELS.map((label) => (
        <button
          key={label}
          type="button"
          onClick={() => onSubmit(label)}
          className="h-7 px-3 rounded-full text-xs font-semibold bg-zinc-800 text-zinc-400 border border-zinc-700 hover:bg-zinc-700 hover:text-zinc-50 hover:border-zinc-600 transition-colors focus:outline-none focus:ring-1 focus:ring-blue-500 focus:ring-offset-1 focus:ring-offset-zinc-950"
        >
          {label}
        </button>
      ))}
    </div>
  );
}
