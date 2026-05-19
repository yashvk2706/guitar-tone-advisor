"""Dense HNSW cosine retrieval over the pgvector ``chunks`` table.

This module is the primary retrieval interface for Phase 2+. It:

1. Expands the user query via ``aliases.expand_query()`` (bidirectional gear
   alias expansion).
2. Embeds the expanded query via the ``Embedder`` Protocol (one call to
   ``embed_query()`` — never ``embed_documents()``).
3. Executes an HNSW cosine-distance scan using the ``<=>`` operator.
4. Returns a ``list[ChunkResult]`` — a typed, frozen dataclass per row.

Security constraints (CLAUDE.md):
- No f-string SQL — all SQL uses ``%s`` parameterised placeholders.
- No direct ``openai`` import — route through ``get_embedder()``.
- pgvector adapter registration is handled by ``get_conn()`` — not here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import psycopg
from pgvector.psycopg import Vector

from app.config import get_settings
from app.db import get_conn
from app.embeddings.base import Embedder
from app.embeddings.factory import get_embedder
from app.retrieval.aliases import expand_query


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkResult:
    """One retrieved chunk with full source metadata.

    Attributes:
        chunk_id:    UUID string (``chunks.id`` cast to text).
        document_id: UUID string (``chunks.document_id`` cast to text).
        source_type: ``'forum'`` | ``'pdf_manual'`` | ``'web_article'`` |
                     ``'youtube'``.
        source_name: Human-readable source identifier — populated from
                     ``metadata_json['source_filename']``.
        chunk_index: 0-based position within the parent document.
        text:        ``chunk_text`` from the DB — the retrievable passage.
        distance:    Cosine DISTANCE via ``<=>`` operator (range 0–2).
                     **Smaller = more similar.**  This is NOT cosine similarity.
                     Do not invert the sort direction in the Phase 5 eval scorer.
    """

    chunk_id: str
    document_id: str
    source_type: str
    source_name: str
    chunk_index: int
    text: str
    distance: float


# ---------------------------------------------------------------------------
# SQL constant — no f-strings (enforced by test_no_fstring_sql_in_base)
# ---------------------------------------------------------------------------

_RETRIEVE_SQL = """
    SELECT
        c.id::text          AS chunk_id,
        c.document_id::text AS document_id,
        c.source_type,
        c.chunk_index,
        c.chunk_text,
        c.metadata_json,
        c.embedding <=> %s  AS distance
    FROM chunks c
    WHERE c.embedding_model = %s
    ORDER BY c.embedding <=> %s
    LIMIT %s
"""


# ---------------------------------------------------------------------------
# Row helper
# ---------------------------------------------------------------------------


def _row_to_chunk_result(row: tuple) -> ChunkResult:
    """Map a DB row tuple to a ``ChunkResult`` dataclass.

    Column order matches ``_RETRIEVE_SQL`` SELECT list:
    ``chunk_id, document_id, source_type, chunk_index, chunk_text,
    metadata_json, distance``.
    """
    chunk_id, document_id, source_type, chunk_index, chunk_text, metadata_json, distance = row
    meta = json.loads(metadata_json) if isinstance(metadata_json, str) else metadata_json
    source_name = meta.get("source_filename", "unknown")
    return ChunkResult(
        chunk_id=chunk_id,
        document_id=document_id,
        source_type=source_type,
        source_name=source_name,
        chunk_index=chunk_index,
        text=chunk_text,
        distance=float(distance),
    )


# ---------------------------------------------------------------------------
# Public retrieval function
# ---------------------------------------------------------------------------


def retrieve(
    query: str,
    k: int = 8,
    *,
    conn: psycopg.Connection | None = None,
    embedder: Embedder | None = None,
) -> list[ChunkResult]:
    """Retrieve the top-``k`` most relevant chunks for ``query``.

    Steps:
    1. Alias-expand the query (bidirectional gear shortform expansion).
    2. Embed the expanded query via ``embedder.embed_query()`` (one call).
    3. Execute HNSW cosine scan with ``embedding_model`` filter.
    4. Map each row to a ``ChunkResult`` and return the list.

    Args:
        query:    Raw user tone query (shortforms OK — expansion is applied).
        k:        Maximum number of results to return (default 8).
                  If fewer than ``k`` chunks exist in the DB, fewer are
                  returned — callers must not assume ``len(results) == k``.
        conn:     Injected psycopg3 connection for testing.  When ``None``,
                  ``get_conn()`` is called (which pre-registers the pgvector
                  adapter).
        embedder: Injected ``Embedder`` instance for testing.  When ``None``,
                  ``get_embedder()`` is called.

    Returns:
        ``list[ChunkResult]`` with 0–``k`` items ordered by ascending cosine
        distance (best match first).
    """
    _conn = conn or get_conn()
    _embedder = embedder or get_embedder()
    embedding_model = get_settings().embedding_model

    expanded = expand_query(query)
    # Wrap in Vector() so psycopg's registered VectorDumper encodes it as the
    # pgvector 'vector' type rather than 'double precision[]'.  In a SELECT the
    # <=> operator has no target-column type context, so an explicit adapter is
    # required (unlike INSERT where the column type provides the cast).
    query_vec = Vector(_embedder.embed_query(expanded))

    with _conn.cursor() as cur:
        cur.execute(_RETRIEVE_SQL, (query_vec, embedding_model, query_vec, k))
        rows = cur.fetchall()
        # EXPLAIN ANALYZE debug logging — emits the query plan to stdout when
        # Settings.debug is True (set DEBUG=true in the environment).
        settings = get_settings()
        if getattr(settings, "debug", False):
            cur.execute(
                "EXPLAIN ANALYZE " + _RETRIEVE_SQL,
                (query_vec, embedding_model, query_vec, k),
            )
            plan_rows = cur.fetchall()
            for plan_row in plan_rows:
                print(plan_row[0])

    return [_row_to_chunk_result(row) for row in rows]
