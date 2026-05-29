"""Idempotent writer for the Phase 1 ingestion pipeline.

This module is the only path that writes to the ``documents``, ``chunks``,
and ``ingest_runs`` tables. It encapsulates two contracts:

1. **Content-hash dedup (INGEST-06).** On re-ingestion of unchanged input no
   embedding API call is wasted: ``chunks_to_embed`` partitions an incoming
   chunk list into ``(to_embed, to_skip)`` by reading the current
   ``(chunk_index, content_hash)`` tuples for the document, and the
   ``upsert_chunks`` ``ON CONFLICT`` clause is the DB-level safety net that
   would catch any partition slip.

2. **Audit lifecycle (T-04-03, T-04-08).** Every CLI invocation flows
   ``start_run`` → ``complete_run`` (success) or ``fail_run`` (exception).
   The pipeline writes the failure row through a *fresh* connection so that
   the audit survives the main transaction's rollback.

Every SQL statement uses psycopg's ``%s`` placeholders. F-string SQL is
forbidden (T-04-01); the ``tests/test_writer.py::test_no_fstring_sql_in_writer``
gate scans this file to enforce it. Vectors are passed as Python ``list[float]``;
the pgvector adapter registered by ``app.db.get_conn`` adapts them to
``vector(1536)`` automatically.
"""

from __future__ import annotations

import json
import uuid
from typing import Sequence

import psycopg

# Stable namespace for deterministic chunk UUIDs derived from content_hash.
# Changing this value would invalidate all existing chunk IDs — never change it.
_CHUNK_NS = uuid.UUID("c4e8b75f-2a3d-4f8e-9b1c-0d2e5f6a7b8c")

from app.ingest.chunker import Chunk
from app.ingest.loader import RawDocument


# ---------------------------------------------------------------------------
# documents upsert
# ---------------------------------------------------------------------------


def upsert_document(conn: psycopg.Connection, raw_doc: RawDocument) -> str:
    """Insert or update one row in ``documents`` and return its UUID.

    Semantics:
        - First call for a given ``(source_type, source_id)`` → INSERT.
        - Subsequent call with the same ``content_hash`` → no-op (the row is
          preserved including its ``fetched_at`` timestamp).
        - Subsequent call with a different ``content_hash`` → UPDATE the
          ``content_hash`` and refresh ``fetched_at``; the UUID is
          preserved.

    The single SQL statement uses ``ON CONFLICT (source_type, source_id) DO
    UPDATE`` with a ``CASE`` expression on ``fetched_at`` so that the no-op
    branch leaves the timestamp untouched. This is the only path Phase 1
    code uses to materialize a ``documents.id`` for the chunks foreign key.
    """

    sql = """
        INSERT INTO documents (source_type, source_id, title, content_hash, fetched_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (source_type, source_id) DO UPDATE SET
            content_hash = EXCLUDED.content_hash,
            fetched_at = CASE
                WHEN documents.content_hash = EXCLUDED.content_hash THEN documents.fetched_at
                ELSE now()
            END,
            title = COALESCE(EXCLUDED.title, documents.title)
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                raw_doc.source_type,
                raw_doc.source_id,
                raw_doc.title,
                raw_doc.content_hash,
            ),
        )
        row = cur.fetchone()
    return str(row[0])


# ---------------------------------------------------------------------------
# chunks partition (application-level dedup before issuing embedding calls)
# ---------------------------------------------------------------------------


def chunks_to_embed(
    conn: psycopg.Connection,
    document_id: str,
    chunks: Sequence[Chunk],
    embedding_model: str,
) -> tuple[list[Chunk], list[Chunk]]:
    """Partition ``chunks`` into ``(to_embed, to_skip)`` by content-hash diff.

    A chunk lands in ``to_skip`` iff a row exists for the same
    ``(document_id, chunk_index, embedding_model)`` AND its stored
    ``content_hash`` matches the incoming chunk's hash.

    Skipping requires the chunk text to be *byte-identical* on re-encode —
    the chunker's ``content_hash`` is sha256 of the NFKC-normalized chunk
    text, so any whitespace drift would change the hash and force a re-embed.
    This is intentional: the contract is "unchanged text wastes no API
    calls", not "approximately unchanged".

    Returns a 2-tuple of lists. Order within each list mirrors the input
    order so the caller can stitch results back by position.
    """

    sql = """
        SELECT chunk_index, content_hash
        FROM chunks
        WHERE document_id = %s AND embedding_model = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (document_id, embedding_model))
        existing: dict[int, str] = {row[0]: row[1] for row in cur.fetchall()}

    to_embed: list[Chunk] = []
    to_skip: list[Chunk] = []
    for c in chunks:
        if existing.get(c.chunk_index) == c.content_hash:
            to_skip.append(c)
        else:
            to_embed.append(c)
    return to_embed, to_skip


# ---------------------------------------------------------------------------
# chunks upsert (vector-aware)
# ---------------------------------------------------------------------------

# Phase 1 ingests only the forum corpus, so chunks rows are written with the
# literal ``'forum'`` source_type. Phase 2 will pass the source_type through
# from the RawDocument when PDF/web/youtube chunkers come online.
_PHASE_1_SOURCE_TYPE = "forum"


def upsert_chunks(
    conn: psycopg.Connection,
    document_id: str,
    chunks: Sequence[Chunk],
    vectors: Sequence[Sequence[float]],
    embedding_model: str,
) -> int:
    """Insert or update one row per chunk in the ``chunks`` table.

    Vector alignment is by position: ``vectors[i]`` is the embedding of
    ``chunks[i]``. A defensive ``assert`` at the top guards against
    misalignment (T-04-02) — silently mis-attributing vectors to chunks
    would corrupt every retrieval result without raising any error, so this
    check is cheap insurance.

    The ``ON CONFLICT (document_id, chunk_index, embedding_model) DO UPDATE``
    clause is the DB-level dedup safety net. The application-level
    ``chunks_to_embed`` partition should mean we never hit a conflict during
    a healthy run; the ``DO UPDATE`` exists so that a content_hash drift
    (e.g., chunker upgrade) cleanly overwrites the prior row rather than
    raising a unique-violation error.

    Returns the integer count of chunks processed (always ``len(chunks)``).
    """

    # T-04-02 mitigation: never write a vector misaligned with its chunk.
    assert len(chunks) == len(vectors), (
        f"chunk/vector length mismatch: {len(chunks)} chunks vs {len(vectors)} vectors"
    )

    if not chunks:
        return 0

    sql = """
        INSERT INTO chunks (
            id, document_id, source_type, chunk_index, chunk_text, content_hash,
            token_count, embedding_model, embedding, metadata_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (document_id, chunk_index, embedding_model) DO UPDATE SET
            chunk_text    = EXCLUDED.chunk_text,
            content_hash  = EXCLUDED.content_hash,
            token_count   = EXCLUDED.token_count,
            embedding     = EXCLUDED.embedding,
            metadata_json = EXCLUDED.metadata_json
    """
    params = [
        (
            str(uuid.uuid5(_CHUNK_NS, c.content_hash)),
            document_id,
            _PHASE_1_SOURCE_TYPE,
            c.chunk_index,
            c.text,
            c.content_hash,
            c.token_count,
            embedding_model,
            list(v),
            json.dumps(c.metadata),
        )
        for c, v in zip(chunks, vectors)
    ]

    with conn.cursor() as cur:
        cur.executemany(sql, params)

    return len(chunks)


# ---------------------------------------------------------------------------
# ingest_runs lifecycle
# ---------------------------------------------------------------------------


def start_run(
    conn: psycopg.Connection,
    embedding_model: str,
    full_rebuild: bool,
) -> str:
    """INSERT a fresh ``ingest_runs`` row with ``status='running'``.

    The row's ``started_at`` is the DB default ``now()``; the caller is
    responsible for flipping it to ``completed`` / ``failed`` via
    ``complete_run`` / ``fail_run``.
    """

    sql = """
        INSERT INTO ingest_runs (embedding_model, full_rebuild, status)
        VALUES (%s, %s, 'running')
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (embedding_model, full_rebuild))
        row = cur.fetchone()
    return str(row[0])


def complete_run(
    conn: psycopg.Connection,
    run_id: str,
    n_documents: int,
    n_chunks_inserted: int,
    n_chunks_skipped: int,
) -> None:
    """Flip an ``ingest_runs`` row to ``completed`` and write its counters."""

    sql = """
        UPDATE ingest_runs SET
            status            = 'completed',
            finished_at       = now(),
            n_documents       = %s,
            n_chunks_inserted = %s,
            n_chunks_skipped  = %s
        WHERE id = %s
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (n_documents, n_chunks_inserted, n_chunks_skipped, run_id),
        )


def fail_run(conn: psycopg.Connection, run_id: str, error: str) -> None:
    """Flip an ``ingest_runs`` row to ``failed`` and record ``error``.

    The pipeline calls this through a **fresh** connection (not the one the
    main transaction rolled back) so the audit trail survives a crash —
    T-04-08 mitigation.

    ``error`` should be ``repr(e)`` rather than ``traceback.format_exc()``
    to avoid leaking SDK-specific request/response bodies into the audit
    row (T-04-05).
    """

    sql = """
        UPDATE ingest_runs SET
            status      = 'failed',
            finished_at = now(),
            error       = %s
        WHERE id = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (error, run_id))


# ---------------------------------------------------------------------------
# Full-rebuild escape hatch (D-04)
# ---------------------------------------------------------------------------


def truncate_all(conn: psycopg.Connection) -> None:
    """TRUNCATE ``chunks`` and ``documents`` with CASCADE.

    Used only by the pipeline's ``--full-rebuild`` flag. ``ingest_runs`` is
    NOT truncated — the audit trail of prior runs is preserved across
    full-rebuilds so the operator can compare counters across re-embeds.

    ``RESTART IDENTITY`` is a no-op for the UUID primary keys but is
    harmless and documents intent.
    """

    sql = "TRUNCATE chunks, documents RESTART IDENTITY CASCADE"
    with conn.cursor() as cur:
        cur.execute(sql)
