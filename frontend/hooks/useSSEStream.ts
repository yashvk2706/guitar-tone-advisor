// SSE streaming hook for POST /api/py/chat
// Implements ReadableStream SSE parser per RESEARCH.md Pattern 6
// Uses fetch() + ReadableStream — EventSource is GET-only (D-05)

export interface CitationSource {
  id: string;        // "S1"
  chunk_id: string;  // UUID
  source_type: string;
  source_name: string;
}

type TokenCallback = (text: string) => void;
type SessionCallback = (sessionId: string) => void;
type CitationsCallback = (sources: CitationSource[]) => void;
type ErrorCallback = (error: Error) => void;

export async function streamChat(
  message: string,
  sessionId: string | null,
  gear: object | null,
  onSession: SessionCallback,
  onToken: TokenCallback,
  onCitations: CitationsCallback,
  onError: ErrorCallback,
  onDone: () => void,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch('/api/py/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message, gear }),
    });
  } catch (err) {
    onError(err instanceof Error ? err : new Error('Network error'));
    onDone();
    return;
  }

  if (!response.ok || !response.body) {
    onError(new Error(`Server error: ${response.status}`));
    onDone();
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE messages are separated by \r\n\r\n (sse-starlette 3.4.4 default)
      // Split on /\r?\n\r?\n/ to handle both \r\n and \n separators (Pitfall 4)
      const events = buffer.split(/\r?\n\r?\n/);
      buffer = events.pop() ?? '';  // last element may be incomplete

      for (const eventBlock of events) {
        if (!eventBlock.trim()) continue;

        const lines = eventBlock.split(/\r?\n/);

        let eventType = '';
        let dataLine = '';

        for (const line of lines) {
          // Skip comment/ping lines starting with ":" (Pitfall 2 mitigation)
          if (line.startsWith(':')) continue;
          if (line.startsWith('event: ')) eventType = line.slice(7).trim();
          if (line.startsWith('data: ')) dataLine = line.slice(6);
        }

        if (!dataLine) continue;

        let parsed: Record<string, unknown>;
        try {
          parsed = JSON.parse(dataLine) as Record<string, unknown>;
        } catch {
          // Malformed JSON — T-03-11 mitigation: trigger error callback
          onError(new Error(`Malformed SSE data: ${dataLine}`));
          continue;
        }

        if (eventType === 'session') {
          if (typeof parsed.session_id === 'string') {
            onSession(parsed.session_id);
          }
        } else if (eventType === 'citations') {
          if (Array.isArray(parsed.sources)) {
            onCitations(parsed.sources as CitationSource[]);
          }
        } else {
          // Plain data: token
          if (typeof parsed.text === 'string' && parsed.text) {
            onToken(parsed.text);
          }
        }
      }
    }
  } catch (err) {
    onError(err instanceof Error ? err : new Error('Stream read error'));
  } finally {
    reader.releaseLock();
    onDone();
  }
}
