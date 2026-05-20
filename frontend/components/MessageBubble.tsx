// Message bubble component per UI-SPEC §2, §3, §10

import { CitationSource } from "@/hooks/useSSEStream";
import CitationPill from "@/components/CitationPill";
import CoverageIndicator from "@/components/CoverageIndicator";

export interface Message {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  citations?: CitationSource[];  // set after event: citations fires (D-08)
  isStreaming?: boolean;         // true while stream is active for this message
}

interface MessageBubbleProps {
  message: Message;
  onCitationClick: (chunkId: string) => void;
}

export default function MessageBubble({ message, onCitationClick }: MessageBubbleProps) {
  // Error bubble (UI-SPEC §10)
  if (message.role === "error") {
    return (
      <div className="flex flex-col gap-2">
        <div className="max-w-[80%] bg-red-950 border border-red-800 rounded-2xl rounded-tl-sm px-4 py-3">
          <p className="text-xs font-medium text-red-400 mb-1">Response failed</p>
          <p className="text-sm text-red-300">
            The server didn&apos;t respond. Check that the FastAPI server is running on port 8000 and try again.
          </p>
        </div>
      </div>
    );
  }

  // User bubble (UI-SPEC §2)
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[70%] bg-zinc-800 rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed text-zinc-50">
          {message.content}
        </div>
      </div>
    );
  }

  // Assistant bubble (UI-SPEC §2, §3, §4, §6)
  // During streaming: append ▋ cursor via CSS after: pseudo-element
  const streamingClass = message.isStreaming
    ? "after:content-['▋'] after:animate-pulse after:text-zinc-400"
    : "";

  return (
    <div className="flex flex-col gap-2">
      <div
        className={`max-w-[80%] bg-zinc-900 rounded-2xl rounded-tl-sm px-4 py-3 text-sm leading-relaxed text-zinc-50 ${streamingClass}`}
      >
        {message.content}
      </div>

      {/* Coverage indicator and citation pills only appear AFTER event:citations fires (D-08) */}
      {message.citations !== undefined && !message.isStreaming && (
        <>
          <CoverageIndicator count={message.citations.length} />
          {message.citations.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {message.citations.map((source) => (
                <CitationPill
                  key={source.id}
                  source={source}
                  onClick={() => onCitationClick(source.chunk_id)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
