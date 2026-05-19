# Phase 2: Retrieval Layer & Gear Aliases - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-18
**Phase:** 02-retrieval-layer-gear-aliases
**Areas discussed:** Alias file scope, Expansion injection, Retrieval result shape

---

## Alias File Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Forum-only (~20 pairs) | Alias only gear directly referenced in the 10 forum post topics. Extend file alongside each future ingestion phase. | ✓ |
| Forum + all 15 manuals (~50 pairs) | Pre-populate all manual gear even though PDFs aren't ingested yet. | |

**User's choice:** Forum-only (~20 pairs)
**Notes:** Chose the recommended option. Reasoning from research: expanding to gear not yet in the index dilutes query vectors with dead tokens and masks retrieval misses during Phase 2 evaluation (can't tell if a miss is an alias bug or a corpus gap).

---

## Expansion Injection

| Option | Description | Selected |
|--------|-------------|----------|
| Replace-in-place | Find alias tokens via word-boundary match, replace with "shortform canonical" (e.g., TS9 → TS9 Ibanez Tube Screamer). Single embed_query() call. | ✓ |
| Append-all-forms | Keep original query, append all alias expansions to end of string. | |

**User's choice:** Replace-in-place
**Notes:** Chose the recommended option. The critical constraint is the Phase 2 success criterion: shortform query and canonical query must retrieve the same top-K chunks. Only replace-in-place achieves this — both normalize toward the same expanded string.

---

## Retrieval Result Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Frozen @dataclass ChunkResult | Typed boundary with chunk_id, document_id, source_type, source_name, chunk_index, text, distance fields. Mirrors EmbeddingResult/Chunk precedent. | ✓ |
| Plain dict list | list[dict] as ROADMAP "chunk dict" language suggests. Zero boilerplate, stringly-typed. | |

**User's choice:** Frozen @dataclass ChunkResult
**Notes:** Chose the recommended option. The codebase already uses frozen dataclasses at every cross-module boundary. A dict at the retrieval→generation boundary risks silent KeyError in the Phase 3 citation XML serializer.

---

## Claude's Discretion

- `app/retrieval/` package structure (mirrors `app/embeddings/`): `__init__.py`, `base.py` (ChunkResult + retrieve function), `aliases.py` (expansion module)
- HNSW SQL: `ORDER BY embedding <=> %s LIMIT %s` with `WHERE embedding_model = %s` filter
- `EXPLAIN ANALYZE` logging gated on `DEBUG=true` env var
- Word-boundary matching via `re.sub(r'\b{re.escape(alias)}\b', replacement, query, flags=re.IGNORECASE)`
- First-occurrence-only expansion to avoid duplication on repeated alias tokens

## Deferred Ideas

None — discussion stayed within phase scope.
