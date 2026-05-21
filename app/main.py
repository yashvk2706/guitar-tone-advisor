"""FastAPI application — POST /chat, GET /sources/{chunk_id}, GET /health.

Wires the generation module and session store into HTTP endpoints.

POST /chat is the core integration point: resolves session, retrieves chunks,
builds prompt, streams generation, appends turns, and emits citations via SSE.

GET /sources/{chunk_id} provides lazy-loaded chunk text for the citation drawer.

CLAUDE.md hard constraints honored here:
    - No f-string SQL — GET /sources/{chunk_id} uses %s::uuid placeholder.
    - No direct openai import — retrieval routes through get_embedder().
    - register_vector() is called by get_conn(), not here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from anthropic import AsyncAnthropic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.db import get_conn
from app.generation.generator import stream_response
from app.generation.prompt import build_messages, build_system_blocks
from app.retrieval.base import retrieve
from app.session import append_turn, get_or_create_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL constant — no f-strings (enforced by test_no_fstring_sql_in_main)
# T-03-07: %s::uuid placeholder rejects any non-UUID string at the DB level
# ---------------------------------------------------------------------------

_SOURCES_SQL = """
    SELECT
        c.id::text         AS chunk_id,
        c.chunk_text,
        c.source_type,
        c.metadata_json,
        d.title,
        d.source_id        AS document_source_id
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE c.id = %s::uuid
"""


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """POST /chat request body (D-15)."""

    session_id: str | None = None
    message: str
    gear: dict | None = None  # only on first turn

    @field_validator("message")
    @classmethod
    def message_not_empty_or_too_long(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be empty")
        if len(v) > 4000:
            raise ValueError("message too long (max 4000 chars)")
        return v


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI()


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Liveness probe — returns {"status": "ok"} with HTTP 200."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /chat — SSE streaming endpoint
# ---------------------------------------------------------------------------


@app.post("/chat")
async def chat(req: ChatRequest):
    """Stream a grounded recommendation as SSE events.

    SSE event sequence (D-06):
    1. ``event: session`` — ``{"session_id": "<uuid>"}``
    2. Plain ``data:`` token chunks — ``{"text": "<token>"}`` (one per token)
    3. ``event: citations`` — ``{"sources": [...]}``

    Session append order (Pitfall 1 from RESEARCH.md):
    - User turn appended BEFORE returning EventSourceResponse.
    - Assistant turn appended inside event_gen() AFTER stream_response exhausts.
    """
    settings = get_settings()
    if settings.anthropic_api_key is None:
        raise HTTPException(
            status_code=500, detail="ANTHROPIC_API_KEY not configured"
        )

    # 1. Resolve session (create on first turn when session_id=null)
    sid = req.session_id or str(uuid.uuid4())
    session = get_or_create_session(sid)

    # 2. Gear injection (D-11): only on first turn
    if req.gear is not None and len(session["turns"]) == 0:
        user_content = f"<gear>{json.dumps(req.gear)}</gear>\n\n{req.message}"
    else:
        user_content = req.message

    # 3. Retrieve relevant chunks — offload blocking IO to thread pool
    loop = asyncio.get_event_loop()
    sources = await loop.run_in_executor(None, retrieve, user_content, 8)

    # 4. Build prompt
    messages = build_messages(session["turns"], user_content, sources)
    system_blocks = build_system_blocks()

    # 5. Append user turn BEFORE streaming (Pitfall 1 prevention)
    append_turn(sid, "user", user_content)

    # 6. Build Anthropic client per request (never at module level)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    # 7. Inner async generator: wraps stream_response, accumulates assistant
    #    response text from token events, then appends assistant turn.
    async def event_gen():
        assistant_parts: list[str] = []
        async for sse_event in stream_response(
            client=client,
            system_blocks=system_blocks,
            messages=messages,
            sources=sources,
            session_id=sid,
        ):
            # Accumulate text from plain data token events (no named event).
            # Named events (session, citations) have sse_event.event set.
            if sse_event.event is None:
                try:
                    payload = json.loads(sse_event.data)
                    if "text" in payload:
                        assistant_parts.append(payload["text"])
                except (json.JSONDecodeError, TypeError):
                    pass
            yield sse_event

        # Append assistant turn after stream completes
        append_turn(sid, "assistant", "".join(assistant_parts))

    # ping=0 disables sse-starlette's 15-second ping comments (Pitfall 2)
    return EventSourceResponse(event_gen(), ping=0)


# ---------------------------------------------------------------------------
# GET /sources/{chunk_id} — citation drawer hydration
# ---------------------------------------------------------------------------


@app.get("/sources/{chunk_id}")
async def get_source(chunk_id: str):
    """Return full chunk text and parent document metadata for a given chunk_id.

    Response shape (D-16):
        {"chunk_id": str, "chunk_text": str, "source_type": str, "source_name": str, "title": str | None}

    Returns 404 if chunk_id is not found or is not a valid UUID (the ``%s::uuid``
    cast rejects non-UUID strings at the Postgres level — T-03-07 mitigation).
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(_SOURCES_SQL, (chunk_id,))
            except Exception as e:
                # Postgres raises DataError for invalid UUID cast — treat as 404
                logger.error("GET /sources/%s query error: %r", chunk_id, e)
                raise HTTPException(status_code=404, detail="Chunk not found")
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Chunk not found")

    # row: (chunk_id_text, chunk_text, source_type, metadata_json, title, document_source_id)
    chunk_id_text, chunk_text, source_type, metadata_json, title, _document_source_id = row

    # Derive source_name from metadata_json->>'source_filename' (same as _row_to_chunk_result)
    meta = (
        json.loads(metadata_json) if isinstance(metadata_json, str) else (metadata_json or {})
    )
    source_name = meta.get("source_filename", "unknown")

    return {
        "chunk_id": chunk_id_text,
        "chunk_text": chunk_text,
        "source_type": source_type,
        "source_name": source_name,
        "title": title,
    }
