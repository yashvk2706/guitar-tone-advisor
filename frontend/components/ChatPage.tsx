"use client";

// Top-level chat orchestration component per UI-SPEC §1
// Manages all React state: sessionId, messages, isStreaming, streamPhase, drawer

type StreamPhase = 'idle' | 'searching' | 'drafting' | 'done';

import { useState, useRef, useEffect, useCallback } from "react";
import { Guitar, ArrowUp, SquarePen } from "lucide-react";
import { streamChat, CitationSource } from "@/hooks/useSSEStream";
import MessageBubble, { Message } from "@/components/MessageBubble";
import CitationDrawer, { DrawerState, DrawerData } from "@/components/CitationDrawer";

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamPhase, setStreamPhase] = useState<StreamPhase>('idle');
  const [inputValue, setInputValue] = useState("");
  const [drawer, setDrawer] = useState<DrawerState | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messageListRef = useRef<HTMLElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const hasFirstTokenRef = useRef(false);

  // Auto-resize textarea up to max-h-[200px]
  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const textarea = e.target;
    setInputValue(textarea.value);
    // Reset height to auto to get accurate scrollHeight
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + "px";
  };

  // Auto-scroll to bottom. Guard: don't hijack scroll when user has scrolled
  // up to read prior messages (threshold 150px gives comfortable reading room).
  const scrollToBottom = useCallback(() => {
    const container = messageListRef.current;
    if (!container) return;
    const isNearBottom =
      container.scrollTop + container.clientHeight >= container.scrollHeight - 150;
    if (isNearBottom) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, []);

  // Scroll on messages changes
  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Handle citation pill click — open drawer, fetch chunk data
  const handleCitationClick = useCallback(async (chunkId: string) => {
    // Immediately show skeleton
    setDrawer({ chunkId, data: null, loading: true, error: false });

    try {
      const res = await fetch(`/api/py/sources/${chunkId}`);
      if (!res.ok) {
        setDrawer((prev) => prev ? { ...prev, loading: false, error: true } : prev);
        return;
      }
      const json = (await res.json()) as DrawerData;
      setDrawer((prev) =>
        prev ? { ...prev, data: json, loading: false, error: false } : prev
      );
    } catch {
      setDrawer((prev) => prev ? { ...prev, loading: false, error: true } : prev);
    }
  }, []);

  const closeDrawer = useCallback(() => {
    setDrawer(null);
  }, []);

  // Submit a message — accepts optional overrideMessage for follow-up button clicks (Plan 04)
  const handleSubmit = useCallback(async (overrideMessage?: string) => {
    const message = overrideMessage !== undefined ? overrideMessage : inputValue.trim();
    if (!message || isStreaming) return;

    // Clear textarea only when user typed the message (not a programmatic override)
    if (overrideMessage === undefined) {
      setInputValue("");
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }
    }

    // Reset first-token flag and transition to 'searching'
    hasFirstTokenRef.current = false;
    setStreamPhase('searching');

    // Add user message to list
    const userId = `user-${Date.now()}`;
    const assistantId = `assistant-${Date.now() + 1}`;

    setMessages((prev) => [
      ...prev,
      { id: userId, role: "user", content: message },
      { id: assistantId, role: "assistant", content: "", isStreaming: true },
    ]);
    setIsStreaming(true);

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    await streamChat(
      message,
      sessionId,
      null, // gear=null for Phase 3 — user types gear in natural language
      // onSession
      (newSessionId: string) => {
        setSessionId(newSessionId);
      },
      // onToken
      (token: string) => {
        // First token: transition searching → drafting
        if (!hasFirstTokenRef.current) {
          hasFirstTokenRef.current = true;
          setStreamPhase('drafting');
        }
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantId
              ? { ...msg, content: msg.content + token }
              : msg
          )
        );
      },
      // onCitations
      (sources: CitationSource[]) => {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantId
              ? { ...msg, citations: sources, isStreaming: false }
              : msg
          )
        );
      },
      // onError
      (_err: Error) => {
        // Replace the empty assistant bubble with an error bubble
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantId
              ? { ...msg, role: "error", content: "", isStreaming: false }
              : msg
          )
        );
        setIsStreaming(false);
        setStreamPhase('idle');
      },
      // onDone
      () => {
        // Mark streaming done (covers case where citations were never emitted)
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantId && msg.isStreaming
              ? { ...msg, isStreaming: false }
              : msg
          )
        );
        setIsStreaming(false);
        setTimeout(() => setStreamPhase('idle'), 300);
        textareaRef.current?.focus();
      },
      abortController.signal,
    );
  }, [inputValue, isStreaming, sessionId]);

  // Enter to submit (not Shift+Enter)
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!isStreaming) {
        handleSubmit();
      }
    }
  };

  // New Chat: abort any in-flight stream, then reset all state
  const handleNewChat = () => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    setSessionId(null);
    setMessages([]);
    setDrawer(null);
    setIsStreaming(false);
    setStreamPhase('idle');
    setInputValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.focus();
    }
  };

  return (
    <div className="flex flex-col h-screen bg-zinc-950 text-zinc-50">
      {/* Header (UI-SPEC §1, §7) */}
      <header className="h-12 flex items-center justify-between px-4 bg-zinc-900 border-b border-zinc-700 shrink-0">
        <span className="text-sm font-semibold text-zinc-50 tracking-wide">
          Guitar Tone Advisor
        </span>
        <button
          onClick={handleNewChat}
          className="h-8 px-3 rounded-md text-xs font-medium bg-zinc-800 text-zinc-300 border border-zinc-700 hover:bg-zinc-700 hover:text-zinc-50 transition-colors flex items-center gap-1.5"
        >
          <SquarePen size={14} />
          New Chat
        </button>
      </header>

      {/* Message list (UI-SPEC §1, §8) */}
      <main
        ref={messageListRef}
        className="flex-1 overflow-y-auto px-4 md:px-16 py-6 space-y-6"
      >
        {messages.length === 0 ? (
          /* Empty state (UI-SPEC §8) */
          <div className="flex flex-col items-center justify-center h-full text-center px-8 gap-4">
            <Guitar size={32} className="text-zinc-600" />
            <h2 className="text-lg font-semibold text-zinc-400">
              Start with your gear
            </h2>
            <p className="text-sm text-zinc-500 max-w-sm leading-relaxed">
              Describe what you&apos;re playing (guitar, amp, pedals) and the tone
              you&apos;re chasing — I&apos;ll cite sources for every recommendation.
            </p>
          </div>
        ) : (
          (() => {
            const lastAssistantIndex = messages.reduce(
              (last, msg, idx) => (msg.role === 'assistant' ? idx : last),
              -1
            );
            return messages.map((msg, index) => {
              const loadingLabel = (msg.isStreaming && streamPhase !== 'idle')
                ? (streamPhase === 'searching' ? 'Searching corpus...' : 'Drafting...')
                : undefined;
              return (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  onCitationClick={handleCitationClick}
                  loadingLabel={loadingLabel}
                  isLatestAssistant={msg.role === 'assistant' && index === lastAssistantIndex}
                  onFollowUp={(text) => handleSubmit(text)}
                />
              );
            });
          })()
        )}
        <div ref={messagesEndRef} />
      </main>

      {/* Input area (UI-SPEC §9) */}
      <footer className="shrink-0 border-t border-zinc-700 bg-zinc-900 p-4">
        <div className="flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={handleTextareaChange}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={isStreaming}
            placeholder="Describe your gear and target tone…"
            className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-sm text-zinc-50 placeholder-zinc-500 resize-none leading-relaxed focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 transition-colors min-h-[48px] disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ maxHeight: "200px" }}
          />
          <button
            onClick={() => handleSubmit()}
            disabled={isStreaming || !inputValue.trim()}
            title="Send message"
            className="ml-2 h-10 w-10 flex items-center justify-center rounded-xl bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:pointer-events-none shrink-0"
          >
            <ArrowUp size={20} />
            <span className="sr-only">Send message</span>
          </button>
        </div>
      </footer>

      {/* Citation drawer (rendered when drawer state is non-null) */}
      {drawer && (
        <CitationDrawer
          drawer={drawer}
          onClose={closeDrawer}
        />
      )}
    </div>
  );
}
