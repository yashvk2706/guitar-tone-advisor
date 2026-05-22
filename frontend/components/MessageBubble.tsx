// Message bubble component per UI-SPEC §2, §3, §10

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import { Copy, Check } from "lucide-react";
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

// Tailwind class mapping for react-markdown rendered elements (UI-SPEC §Typography)
const MARKDOWN_COMPONENTS: Components = {
  p: ({ children }) => (
    <p className="text-sm text-zinc-50 leading-relaxed my-1">{children}</p>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-zinc-50">{children}</strong>
  ),
  em: ({ children }) => (
    <em className="italic text-zinc-200">{children}</em>
  ),
  h1: ({ children }) => (
    <h1 className="text-base font-semibold text-zinc-50 mt-3 mb-1">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-sm font-semibold text-zinc-200 mt-3 mb-1">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-sm font-semibold text-zinc-300 mt-2 mb-1">{children}</h3>
  ),
  ul: ({ children }) => (
    <ul className="list-disc list-inside space-y-1 my-1 text-sm">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="list-decimal list-inside space-y-1 my-1 text-sm">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="text-zinc-200">{children}</li>
  ),
  // Block code: pre renders the block with bg; code inside gets font/color only (no bg)
  pre: ({ children }) => (
    <pre className="bg-zinc-800 rounded-lg p-3 overflow-x-auto my-2">{children}</pre>
  ),
  // Inline code vs block code: block code is always a child of pre (handled above).
  // This renderer is only invoked for inline code (react-markdown renders block code
  // as <pre><code> so both renderers fire; the pre wrapper handles the bg).
  code: ({ children, className }) => {
    // className is set for fenced code blocks (e.g. "language-js") — treat as block code
    const isBlock = Boolean(className);
    if (isBlock) {
      return (
        <code className="font-mono text-xs text-emerald-300 leading-relaxed">
          {children}
        </code>
      );
    }
    // Inline code
    return (
      <code className="font-mono text-xs bg-zinc-800 text-emerald-300 px-1 rounded">
        {children}
      </code>
    );
  },
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-zinc-600 pl-3 text-zinc-400 italic my-1">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="border-zinc-700 my-2" />,
  a: ({ href, children }) => (
    <a
      href={href}
      className="text-blue-400 underline hover:text-blue-300"
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
    </a>
  ),
};

export default function MessageBubble({ message, onCitationClick }: MessageBubbleProps) {
  const [copied, setCopied] = useState(false);

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
  // Streaming cursor (▋) is on the outer bubble wrapper div — not inside ReactMarkdown
  // content — to avoid the cursor appearing inside a <p> or <li> (UI-SPEC §Component
  // Contracts §1 streaming behavior note).
  const streamingClass = message.isStreaming
    ? "after:content-['▋'] after:animate-pulse after:text-zinc-400"
    : "";

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="flex flex-col gap-2">
      <div
        className={`relative group max-w-[80%] bg-zinc-900 rounded-2xl rounded-tl-sm px-4 py-3 ${streamingClass}`}
      >
        {/* Copy button — visible on hover (UI-SPEC §7) */}
        <button
          onClick={handleCopy}
          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity h-6 w-6 flex items-center justify-center rounded text-zinc-700 hover:text-zinc-400 hover:bg-zinc-800"
          title={copied ? "Copied!" : "Copy response"}
        >
          {copied ? (
            <Check size={14} className="text-green-500" />
          ) : (
            <Copy size={14} />
          )}
        </button>

        {/* Markdown-rendered content */}
        <div className="space-y-1">
          <ReactMarkdown components={MARKDOWN_COMPONENTS}>
            {message.content}
          </ReactMarkdown>
        </div>
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
