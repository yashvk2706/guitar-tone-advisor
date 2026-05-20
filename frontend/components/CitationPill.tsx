// Citation pill: [S1], [S2], etc. per UI-SPEC §4

import { CitationSource } from "@/hooks/useSSEStream";

interface CitationPillProps {
  source: CitationSource;
  onClick: () => void;
}

export default function CitationPill({ source, onClick }: CitationPillProps) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center h-5 px-1.5 rounded text-xs font-medium font-mono bg-blue-950 text-blue-400 border border-blue-800 cursor-pointer hover:bg-blue-900 hover:text-blue-300 hover:border-blue-600 transition-colors focus:outline-none focus:ring-1 focus:ring-blue-500 focus:ring-offset-1 focus:ring-offset-zinc-950"
    >
      [{source.id}]
    </button>
  );
}
