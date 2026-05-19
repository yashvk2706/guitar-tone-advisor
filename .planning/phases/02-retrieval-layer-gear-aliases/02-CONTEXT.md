# Phase 2: Retrieval Layer & Gear Aliases - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire HNSW cosine retrieval through the `Embedder` Protocol with bidirectional gear-alias query expansion. A guitarist's free-text tone query (with shortforms like "TS9" or "JCM800") returns the top-8 most relevant forum chunks with full source metadata, after bidirectional alias expansion is applied to the query before embedding.

**In scope:** `gear_aliases.json` authoring (forum corpus only), bidirectional alias expansion module, dense HNSW retrieval function (K=8, cosine distance), metadata-preserving `ChunkResult` envelope, retrieval unit tests.

**Out of scope:** PDF/article/YouTube ingestion (v2), hybrid tsvector+RRF retrieval (Phase 5), FastAPI endpoint (Phase 3), any generation or UI (Phase 3+). Do NOT pre-alias gear from manuals not yet ingested.

</domain>

<decisions>
## Implementation Decisions

### Alias File Scope
- **D-01:** `gear_aliases.json` covers **forum-corpus-only** — approximately 15–20 bidirectional alias pairs derived directly from the 10 forum post topics (TS9, JCM800, Strat, Tele, EVH/5150, etc.). Every entry must be justified by actual text in an ingested chunk. Manuals are NOT pre-aliased even though the PDFs are on disk — that work belongs inside each future ingestion phase.
- **D-02:** The file grows as a checklist item in each subsequent ingestion phase (manuals → Phase 2 v2, articles/YouTube → later). No open-ended "all common shortforms" expansion.

### Expansion Injection
- **D-03:** Use **replace-in-place** expansion: find alias tokens in the query string via word-boundary matching and replace each with `"<shortform> <canonical>"` (e.g., `"TS9"` → `"TS9 Ibanez Tube Screamer"`). Bidirectional — canonical forms are also expanded to include their shortform (e.g., `"Tube Screamer"` → `"TS9 Tube Screamer"`).
- **D-04:** A single `embed_query(expanded_text)` call is issued after expansion. No multi-vector averaging, no append-to-end style. This satisfies the Phase 2 success criterion: shortform query and canonical query produce near-identical expanded strings → near-identical embedding → same top-K chunks.
- **D-05:** Implementation must use word-boundary matching (not naive `str.replace`) to avoid mangling substrings. Case-insensitive matching. If an alias token appears multiple times in the query, expand only the first occurrence to avoid duplication.

### Retrieval Result Shape
- **D-06:** The retrieval function returns `list[ChunkResult]` where `ChunkResult` is a `@dataclass(frozen=True)` defined in `app/retrieval/base.py`. Fields: `chunk_id: str`, `document_id: str`, `source_type: str`, `source_name: str`, `chunk_index: int`, `text: str`, `distance: float` (cosine distance, for eval/debug). Mirrors `EmbeddingResult` and `Chunk` precedents.
- **D-07:** No plain `list[dict]` return — the Phase 3 citation XML serializer must access typed fields. A stringly-keyed dict at this boundary risks silent `KeyError` on `source_name` vs `source` typos in the generation layer.

### Claude's Discretion
- Module placement: `app/retrieval/` package with `__init__.py`, `base.py` (ChunkResult + retrieve function), `aliases.py` (gear alias expansion). Mirrors `app/embeddings/` structure.
- HNSW search SQL: use `<=>` cosine operator (already indexed on `chunks_embedding_hnsw_cos`). Include `WHERE embedding_model = %s` filter to guard against future model mixing. `ORDER BY embedding <=> %s LIMIT %s`.
- `register_vector(conn)` is called automatically by `get_conn()` — retrieval code just calls `get_conn()`, no extra registration needed.
- `EXPLAIN ANALYZE` logging in dev: log the query plan to stdout when `DEBUG=true` env var is set (or a settings flag). Not a hard requirement for Phase 2, but called out in the ROADMAP.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Scope
- `.planning/REQUIREMENTS.md` §v1 Requirements — INGEST-07, RETR-01, RETR-02, RETR-03 define all Phase 2 acceptance criteria
- `.planning/ROADMAP.md` §Phase 2 — 3 plans, success criteria, and what's deferred

### Architecture & Schema
- `.planning/research/ARCHITECTURE.md` §Retrieval — HNSW cosine search, gear alias expansion, result envelope spec
- `scripts/init_db.sql` — `chunks_embedding_hnsw_cos` HNSW index definition (`vector_cosine_ops`, `m=16, ef_construction=64`)

### Phase 1 Established Patterns (MANDATORY — Phase 2 must follow these)
- `app/db.py` — `get_conn()` pattern: opens psycopg3 connection with `register_vector(conn)` pre-called; retrieval code MUST go through `get_conn()`, never open connections directly
- `app/embeddings/base.py` — `Embedder` Protocol: `embed_query(text: str) -> list[float]` is the retrieval layer's embedding interface; call this once with the expanded query string
- `app/embeddings/factory.py` — `get_embedder()` factory: how the retrieval layer obtains an `Embedder` instance
- `app/ingest/chunker.py` — `Chunk` dataclass pattern: frozen dataclass at module boundary; `ChunkResult` must follow the same convention
- `CLAUDE.md` §Architecture — retrieval uses `<=>` (`vector_cosine_ops`); no f-string SQL; all external API calls wrapped with tenacity

### Stack & Dependencies
- `.planning/research/STACK.md` §pgvector Schema — HNSW retrieval query template using `<=>` operator
- `.planning/research/STACK.md` §Recommended Stack Summary — pinned versions (psycopg[binary] 3.3.4, pgvector 0.4.2)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/db.get_conn()` — retrieval's only path to a DB connection; already registers pgvector adapter
- `app/embeddings/factory.get_embedder()` — returns a configured `Embedder` instance; retrieval calls `embedder.embed_query(expanded_query)` directly
- `app/embeddings/base.EmbeddingResult` — frozen dataclass pattern to mirror for `ChunkResult`
- `app/ingest/chunker.Chunk` — frozen dataclass with typed fields; the structural template for `ChunkResult`

### Established Patterns
- **Frozen dataclass at module boundary** — `EmbeddingResult` (embeddings → writer), `Chunk` (loader → chunker → writer). `ChunkResult` (retrieval → generation) follows the same convention.
- **No f-string SQL** — enforced by a grep test in `tests/test_writer.py`; retrieval SQL must use `%s` placeholders only.
- **psycopg3 not psycopg2** — `import psycopg` (v3); vectors passed as `list[float]` via pgvector adapter.
- **Settings via `app.config.get_settings()`** — `EMBEDDING_MODEL` env var drives embedder selection; retrieval inherits this via the factory.

### Integration Points
- **Input:** User query string (raw, from Phase 3 chat layer) → alias expansion → `embed_query()` → `list[float]`
- **Output:** `list[ChunkResult]` passed to Phase 3 generation module, which formats them as `<sources>` XML with `S1..Sn` IDs for `[Sn]` citation
- **DB:** `chunks` table — `chunk_text`, `source_type`, `metadata_json` (contains `source_filename`), `embedding_model` filter, HNSW cosine index
- **documents table:** `source_id` (source filename/name) joinable from `document_id` on the chunks row

</code_context>

<specifics>
## Specific Ideas

- `gear_aliases.json` entries must be grounded in actual forum post text — inspect `raw_data/forum_posts/*.txt` to derive the alias pairs rather than guessing from general guitar knowledge.
- Replace-in-place expansion: word-boundary match is critical. "TS9" must not expand inside "TS9-style" in a way that corrupts the phrase. Use `re.sub(r'\b{re.escape(alias)}\b', replacement, query, flags=re.IGNORECASE)`.
- `ChunkResult.distance` is cosine distance (not similarity) — smaller value = closer match. Document this in the field's type annotation comment so Phase 5 eval scorer doesn't flip the sort direction.
- The retrieval function signature should be: `retrieve(query: str, k: int = 8, *, conn: psycopg.Connection | None = None, embedder: Embedder | None = None) -> list[ChunkResult]` — injectable dependencies for unit testing (same pattern as Phase 1 writer tests that inject connections).

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 2-Retrieval-Layer-Gear-Aliases*
*Context gathered: 2026-05-18*
