// Citation drawer: right-side overlay with source-type badge, chunk text per UI-SPEC §5

import { X } from "lucide-react";

export interface DrawerData {
  chunk_text: string;
  source_type: string;
  source_name: string;
  title: string | null;
}

export interface DrawerState {
  chunkId: string;
  data: DrawerData | null;
  loading: boolean;
  error: boolean;
}

interface CitationDrawerProps {
  drawer: DrawerState;
  onClose: () => void;
}

// Source type → badge label mapping (CONTEXT.md §Specific Ideas)
const SOURCE_TYPE_LABELS: Record<string, string> = {
  forum: "[Forum]",
  pdf_manual: "[Manual]",
  web_article: "[Article]",
  youtube: "[YouTube]",
};

// Source type → badge color classes (UI-SPEC §5)
const SOURCE_TYPE_BADGE_CLASSES: Record<string, string> = {
  forum: "bg-emerald-950 text-emerald-400 border border-emerald-800",
  pdf_manual: "bg-amber-950 text-amber-400 border border-amber-800",
  web_article: "bg-violet-950 text-violet-400 border border-violet-800",
  youtube: "bg-rose-950 text-rose-400 border border-rose-800",
};

export default function CitationDrawer({ drawer, onClose }: CitationDrawerProps) {
  const badgeLabel = SOURCE_TYPE_LABELS[drawer.data?.source_type ?? ''] ?? `[${drawer.data?.source_type ?? '?'}]`;
  const badgeClasses = SOURCE_TYPE_BADGE_CLASSES[drawer.data?.source_type ?? ''] ?? "bg-zinc-800 text-zinc-400 border border-zinc-700";

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer panel */}
      <div className="fixed right-0 top-0 h-full w-80 md:w-96 bg-zinc-900 border-l border-zinc-700 z-50 flex flex-col">
        {/* Header row */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700 shrink-0">
          {drawer.loading ? (
            <div className="h-4 bg-zinc-700 rounded animate-pulse flex-1 mr-2" />
          ) : drawer.data ? (
            <>
              <span
                className={`inline-flex items-center h-5 px-1.5 rounded text-xs font-medium font-mono shrink-0 ${badgeClasses}`}
              >
                {badgeLabel}
              </span>
              <span className="text-xs text-zinc-400 font-normal truncate flex-1 mx-2">
                {drawer.data.source_name}
              </span>
            </>
          ) : (
            <span className="text-xs text-zinc-400 font-mono flex-1">Source</span>
          )}

          <button
            onClick={onClose}
            className="h-6 w-6 flex items-center justify-center text-zinc-400 hover:text-zinc-50 rounded hover:bg-zinc-700 transition-colors shrink-0"
            title="Close"
          >
            <X size={16} />
          </button>
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-y-auto">
          {drawer.loading && (
            <div className="space-y-2 mx-4 my-3">
              <div className="h-4 bg-zinc-700 rounded animate-pulse" />
              <div className="h-4 bg-zinc-700 rounded animate-pulse" />
              <div className="h-4 bg-zinc-700 rounded animate-pulse" />
            </div>
          )}

          {drawer.error && !drawer.loading && (
            <p className="text-xs text-red-400 font-mono mx-4 my-3">
              Failed to load source. Try again.
            </p>
          )}

          {drawer.data && !drawer.loading && (
            <div className="mx-4 mb-4 mt-4 p-3 bg-zinc-800 rounded-lg text-xs font-mono leading-relaxed text-zinc-300 overflow-y-auto max-h-[calc(100vh-8rem)]">
              {drawer.data.chunk_text}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
