"""Streaming generation with post-stream citation validation.

This module implements the core SSE streaming generator that:
1. Emits ``event: session`` first (idempotent session ID confirmation).
2. Streams tokens from the Anthropic API via ``AsyncMessageStream.text_stream``.
3. Accumulates the full response text after the stream completes.
4. Validates ``[Sn]`` citations against the injected sources list (D-08, D-09).
5. Emits ``event: citations`` last with only valid, in-range source IDs.

Security constraints (CLAUDE.md / threat model):
    - No direct openai import (T-03-02 guard; also enforced by static test).
    - ANTHROPIC_API_KEY must not appear in logs — use repr(e), never
      traceback.format_exc() in error handlers (T-03-02).
    - register_vector() must NOT be called here — that is app/db.py's job.
    - Citation regex runs exactly once, after stream completes (D-08).
      Never run it against partial text during streaming (Pitfall 5).
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from sse_starlette.event import ServerSentEvent

from app.config import get_settings
from app.retrieval.base import ChunkResult


# ---------------------------------------------------------------------------
# Module-level compiled regex — avoids recompile on each call (D-09)
# ---------------------------------------------------------------------------

_CITATION_RE = re.compile(r"\[S(\d+)\]")


# ---------------------------------------------------------------------------
# Public async generator
# ---------------------------------------------------------------------------


async def stream_response(
    *,
    client: AsyncAnthropic,
    system_blocks: list[dict],
    messages: list[dict],
    sources: list[ChunkResult],
    session_id: str,
) -> AsyncIterator[ServerSentEvent]:
    """Yield SSE events: session → token data → citations.

    Event sequence (D-06):
    1. ``event: session`` — ``{"session_id": "<uuid>"}`` — always emitted first.
    2. Plain ``data:`` token chunks — ``{"text": "<token>"}`` — one per token.
    3. ``event: citations`` — ``{"sources": [...]}`` — always emitted last.

    The citations payload contains only validated source IDs where the
    referenced [Sn] index n satisfies ``1 <= n <= len(sources)``. Out-of-range
    citations are silently discarded (T-03-03 mitigation).

    Args:
        client:        Injected AsyncAnthropic instance. Tests pass a
                       ``_FakeAnthropicClient`` that yields predetermined tokens.
        system_blocks: list of TextBlockParam dicts (with cache_control) from
                       ``build_system_blocks()``.
        messages:      Anthropic MessageParam list from ``build_messages()``.
        sources:       The retrieved ChunkResult list for this turn. Used for
                       citation validation and building the citations payload.
        session_id:    UUID string for this session — echoed back in the first
                       event so the client can store it.

    Yields:
        ``ServerSentEvent`` objects in the order: session → tokens → citations.
    """
    # 1. Session event — always first, even on follow-up turns (idempotent)
    yield ServerSentEvent(
        data=json.dumps({"session_id": session_id}),
        event="session",
    )

    full_response: list[str] = []

    # 2. Stream tokens — accumulate in parallel with yielding (Pitfall 5 prevention:
    #    citation regex does NOT run here; only appends to full_response list)
    async with client.messages.stream(
        model=get_settings().anthropic_model,
        max_tokens=1024,
        system=system_blocks,
        messages=messages,
        temperature=0.1,
    ) as stream:
        async for text in stream.text_stream:
            full_response.append(text)
            yield ServerSentEvent(data=json.dumps({"text": text}))

    # 3. Post-stream citation validation — runs exactly once after stream ends (D-08)
    response_text = "".join(full_response)
    raw_ns = {int(n) for n in _CITATION_RE.findall(response_text)}
    valid_ns = {n for n in raw_ns if 1 <= n <= len(sources)}

    citations_payload = [
        {
            "id": f"S{n}",
            "chunk_id": sources[n - 1].chunk_id,
            "source_type": sources[n - 1].source_type,
            "source_name": sources[n - 1].source_name,
        }
        for n in sorted(valid_ns)
    ]

    # 4. Citations event — always last
    yield ServerSentEvent(
        data=json.dumps({"sources": citations_payload}),
        event="citations",
    )
