-- Idempotent: safe to run multiple times. Phase 1 schema (D-05, D-06).
--
-- Run once before the ingestion pipeline:
--     psql "$DATABASE_URL" -f scripts/init_db.sql
--
-- The target database is assumed to exist already; this script does NOT
-- issue CREATE DATABASE. All objects use IF NOT EXISTS so the script is a
-- safe no-op on a populated database.

-- Required extensions ---------------------------------------------------------
-- pgcrypto for gen_random_uuid() (core in PG13+, but explicit for portability).
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- pgvector for the vector(1536) column + HNSW cosine index.
CREATE EXTENSION IF NOT EXISTS vector;
-- pg_trgm pre-installed in Phase 1 for Phase 3 hybrid-search headroom (D-06).
CREATE EXTENSION IF NOT EXISTS pg_trgm;


-- documents -------------------------------------------------------------------
-- One row per ingested source file. UNIQUE(source_type, source_id) lets the
-- writer upsert deterministically: source_id = filename (forum), URL (web),
-- video_id (youtube), or path-stem (pdf_manual).
CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type     TEXT NOT NULL CHECK (source_type IN ('forum','pdf_manual','web_article','youtube')),
    source_id       TEXT NOT NULL,
    title           TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_hash    TEXT NOT NULL,
    metadata_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_type, source_id)
);


-- chunks ----------------------------------------------------------------------
-- One row per embedded passage. UNIQUE(document_id, chunk_index, embedding_model)
-- enables content-hash dedup keyed on stable chunk identity even when the
-- embedding_model env var changes (re-embed produces a new row, not a clash).
CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL,
    chunk_index     INTEGER NOT NULL,
    chunk_text      TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    token_count     INTEGER,
    embedding_model TEXT NOT NULL,
    embedding       vector(1536) NOT NULL,
    metadata_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index, embedding_model)
);


-- ingest_runs -----------------------------------------------------------------
-- Audit log: one row per CLI invocation of `python -m app.ingest.pipeline`.
CREATE TABLE IF NOT EXISTS ingest_runs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    embedding_model   TEXT,
    n_documents       INTEGER NOT NULL DEFAULT 0,
    n_chunks_inserted INTEGER NOT NULL DEFAULT 0,
    n_chunks_skipped  INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','completed','failed')),
    error             TEXT,
    full_rebuild      BOOLEAN NOT NULL DEFAULT FALSE
);


-- Indexes ---------------------------------------------------------------------
-- HNSW for cosine similarity. m=16, ef_construction=64 per D-06 (research
-- defaults, sane for <100K-chunk corpora). HNSW works on an empty table —
-- IVFFlat does not.
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_cos
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Supporting btree indexes for filtered retrieval.
CREATE INDEX IF NOT EXISTS chunks_document_id_idx     ON chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_embedding_model_idx ON chunks (embedding_model);
CREATE INDEX IF NOT EXISTS chunks_source_type_idx     ON chunks (source_type);

-- Trigram index reserved for Phase 3 hybrid (BM25-ish) search (D-06).
CREATE INDEX IF NOT EXISTS chunks_text_trgm_idx
    ON chunks USING gin (chunk_text gin_trgm_ops);
