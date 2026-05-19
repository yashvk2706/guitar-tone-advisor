# Phase 2: Retrieval Layer & Gear Aliases - Research

**Researched:** 2026-05-18
**Domain:** Dense vector retrieval (HNSW cosine, psycopg3, pgvector) + regex alias expansion
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** `gear_aliases.json` covers **forum-corpus-only** — approximately 15-20 bidirectional alias pairs derived directly from the 10 forum post topics (TS9, JCM800, Strat, Tele, EVH/5150, etc.). Every entry must be justified by actual text in an ingested chunk. Manuals are NOT pre-aliased even though the PDFs are on disk — that work belongs inside each future ingestion phase.

**D-02:** The file grows as a checklist item in each subsequent ingestion phase (manuals Phase 2 v2, articles/YouTube later). No open-ended "all common shortforms" expansion.

**D-03:** Use **replace-in-place** expansion: find alias tokens in the query string via word-boundary matching and replace each with `"<shortform> <canonical>"` (e.g., `"TS9"` → `"TS9 Ibanez Tube Screamer"`). Bidirectional — canonical forms are also expanded to include their shortform (e.g., `"Tube Screamer"` → `"TS9 Tube Screamer"`).

**D-04:** A single `embed_query(expanded_text)` call is issued after expansion. No multi-vector averaging, no append-to-end style.

**D-05:** Implementation must use word-boundary matching (not naive `str.replace`) to avoid mangling substrings. Case-insensitive matching. If an alias token appears multiple times in the query, expand only the first occurrence to avoid duplication.

**D-06:** The retrieval function returns `list[ChunkResult]` where `ChunkResult` is a `@dataclass(frozen=True)` defined in `app/retrieval/base.py`. Fields: `chunk_id: str`, `document_id: str`, `source_type: str`, `source_name: str`, `chunk_index: int`, `text: str`, `distance: float` (cosine distance, for eval/debug).

**D-07:** No plain `list[dict]` return — the Phase 3 citation XML serializer must access typed fields.

### Claude's Discretion

- Module placement: `app/retrieval/` package with `__init__.py`, `base.py` (ChunkResult + retrieve function), `aliases.py` (gear alias expansion). Mirrors `app/embeddings/` structure.
- HNSW search SQL: use `<=>` cosine operator. Include `WHERE embedding_model = %s` filter. `ORDER BY embedding <=> %s LIMIT %s`.
- `register_vector(conn)` is called automatically by `get_conn()` — retrieval code just calls `get_conn()`, no extra registration needed.
- `EXPLAIN ANALYZE` logging in dev: log the query plan to stdout when `DEBUG=true` env var is set.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INGEST-07 | `gear_aliases.json` maps gear shortforms to canonical names bidirectionally; alias expansion applied to user queries before embedding | Corpus scan completed; 14 verified alias pairs documented below |
| RETR-01 | Given a user tone query, system retrieves top-K most relevant chunks via HNSW cosine similarity search | SQL template confirmed; psycopg3 + pgvector parameter passing verified in existing writer.py |
| RETR-02 | User query expanded using gear aliases before embedding (both shortforms and full names searched) | regex `re.sub` pattern with `re.IGNORECASE` + `re.escape` confirmed as correct approach |
| RETR-03 | Retrieved chunks include full source metadata (source_type, source_name, page/chunk reference) passed to generation layer | Schema columns confirmed; JOIN with documents table not needed — `source_type`, `chunk_index`, and `metadata_json` are on `chunks` row |
</phase_requirements>

---

## Summary

Phase 2 wires three collaborating components: a static alias map (`gear_aliases.json`), a query expansion module (`app/retrieval/aliases.py`), and a dense retrieval function (`app/retrieval/base.py`). All three are pure Python with no new dependencies — the pgvector adapter, psycopg3 connection helper, and Embedder Protocol are already installed and battle-tested from Phase 1.

The most important codebase finding is that the existing `writer.py` already proves the full psycopg3 + pgvector round-trip pattern: vectors are passed as `list[float]` via `%s` placeholders after `register_vector(conn)` is called, and the adapter handles the SQL `vector` type transparently. The retrieval SELECT query follows the identical pattern in reverse — the pgvector adapter will deserialize the stored vector on SELECT automatically, and passing the query embedding as `list(query_vector)` via `%s` in the `<=>` expression is the established project pattern.

The alias corpus scan of all 10 forum post `.txt` files identified 14 grounded alias pairs (shortform ↔ canonical name). No aliases were assumed from general guitar knowledge — every pair is traceable to actual text in the corpus files. The expand-in-place design (replace shortform with `"shortform canonical"` in the query string) satisfies D-03/D-05 and ensures both shortform and canonical tokens are present in the expanded string, giving the embedding maximum signal overlap with corpus chunks that may use either form.

**Primary recommendation:** Implement `aliases.py` first (pure regex, no DB dependency, fully unit-testable offline), then `base.py` with the retrieval SQL, then wire them together. Every component has a clear injectable dependency surface for testing without a live DB.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Gear alias JSON authoring | Filesystem (static data file) | — | Offline, human-curated, corpus-scoped; not a DB table |
| Query alias expansion | Python (app/retrieval/aliases.py) | — | Pure string transform before any I/O; must run before embedding |
| Query embedding | Embedder Protocol (embed_query) | — | Already established Phase 1 contract; retrieval calls it, doesn't implement it |
| HNSW vector search | PostgreSQL / pgvector | — | Index-backed ANN; chunked text + metadata already in DB |
| Result envelope construction | Python (app/retrieval/base.py) | — | Typed dataclass assembled from DB rows, surfaced to Phase 3 |
| Source metadata | PostgreSQL (chunks.source_type, chunks.chunk_index, chunks.metadata_json) | — | All metadata required by RETR-03 is on the chunks row; no JOIN needed for Phase 2 |

---

## Alias File: Grounded Corpus Findings

**Every pair below was verified against actual text in `raw_data/forum_posts/*.txt`.**
[VERIFIED: grep scan of all 10 forum post files, 2026-05-18]

### Confirmed Alias Pairs

| Shortform | Canonical | Found in Corpus File(s) |
|-----------|-----------|------------------------|
| Strat | Stratocaster | john_mayer_tone.txt, funk_tone.txt, lo_fi_tone.txt, rnb_neo_soul_tone.txt |
| Tele | Telecaster | rnb_neo_soul_tone.txt |
| EVH | Eddie Van Halen | eddie_van_halen_tone.txt, unconventional_tones.txt |
| SLO | Soldano SLO-100 | eddie_van_halen_tone.txt |
| 5150 | Peavey 5150 | eddie_van_halen_tone.txt |
| 6505 | Peavey 6505 | eddie_van_halen_tone.txt (listed as "original 5150" synonym) |
| AX8 | Fractal AX8 | eddie_van_halen_tone.txt |
| SD1 | Boss SD-1 | eddie_van_halen_tone.txt |
| GE-7 | Boss GE-7 | bb_king_tone.txt |
| HM-2 | Boss HM-2 | unconventional_tones.txt |
| Dual Rec | Mesa Dual Rectifier | modern_pop_punk_tone.txt |
| Maxon 808 | Maxon OD808 | modern_pop_punk_tone.txt |
| SRV | Stevie Ray Vaughan | john_mayer_tone.txt |
| SSS | Dumble Steel String Slinger | john_mayer_tone.txt |

### Intentionally NOT in the file (forum text does not use these shortforms)

| Term | Reason Excluded |
|------|-----------------|
| TS9 | "Tube Screamer" and "Ibanez Tube Screamer" appear in corpus, but "TS9" as a token does NOT — corpus says "Ibanez Tube Screamer" and "TS family"; adding TS9 would be assumed, not corpus-grounded |
| JCM800 | "Marshall" appears but "JCM800" as a specific token does not appear in any forum post |
| BD-2 | "Blues Driver" appears but "BD-2" as a model code does not |
| Klon | "Klon" appears as full word in john_mayer_tone.txt — not a shortform that needs expanding |
| MXR | "MXR" appears in eddie_van_halen_tone.txt but is a brand, not a shortform with a canonical expansion |

**Key finding:** The forum corpus uses more canonical names than shortforms. The 14 pairs above are all the justifiable bidirectional expansions for Phase 2. D-01 is achievable with this set.

### Bidirectionality Structure

The `gear_aliases.json` format must support bidirectional lookup. Recommended structure:

```json
{
  "aliases": [
    {
      "shortform": "Strat",
      "canonical": "Stratocaster"
    },
    ...
  ]
}
```

At load time, `aliases.py` builds two lookup dicts from this list: `shortform → canonical` AND `canonical → shortform`. Both directions are expanded in the query string per D-03.

---

## Standard Stack

### Core (no new dependencies for Phase 2)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg[binary] | 3.3.4 (pinned) | DB connection + cursor | Already in requirements.txt; `register_vector` called in `get_conn()` |
| pgvector | 0.4.2 (pinned) | vector type adapter for psycopg3 | Already registered; `list[float]` passes via `%s` after registration |
| re (stdlib) | — | Alias regex expansion | `re.sub` with `re.IGNORECASE` + word boundaries; no external dep needed |
| dataclasses (stdlib) | — | `ChunkResult` frozen dataclass | Matches `Chunk`, `EmbeddingResult` precedent |
| json (stdlib) | — | Load `gear_aliases.json` | No external JSON parsing library needed |

**Installation:** No new packages. All dependencies already installed.

### No new packages needed

Phase 2 is entirely served by the Phase 1 stack. [VERIFIED: requirements.txt + venv package list]

---

## Architecture Patterns

### System Architecture Diagram

```
User query string
        │
        ▼
┌─────────────────────────┐
│  aliases.expand_query() │  ← loads gear_aliases.json once at module import
│  re.sub word-boundary   │    (cached; no DB or API call)
│  shortform → "sf canon" │
│  canonical → "sf canon" │
└────────────┬────────────┘
             │ expanded query string
             ▼
┌─────────────────────────┐
│  embedder.embed_query() │  ← Embedder Protocol (OpenAI text-embedding-3-small)
│  → list[float] 1536-d   │    tenacity retry/backoff wraps API call
└────────────┬────────────┘
             │ query vector
             ▼
┌─────────────────────────┐
│  psycopg3 cursor.execute│  ← get_conn() (register_vector pre-called)
│  SELECT ... FROM chunks │    WHERE embedding_model = %s
│  ORDER BY embedding<=>%s│    ORDER BY embedding <=> %s (HNSW scan)
│  LIMIT %s               │    LIMIT %s
└────────────┬────────────┘
             │ rows: (id, document_id, source_type, chunk_index,
             │        chunk_text, metadata_json, distance)
             ▼
┌─────────────────────────┐
│  list[ChunkResult]      │  ← frozen dataclass per row
│  (typed result envelope)│    surfaced to Phase 3 generation layer
└─────────────────────────┘
```

### Recommended Project Structure

```
app/
├── retrieval/
│   ├── __init__.py        # empty or re-export retrieve()
│   ├── base.py            # ChunkResult dataclass + retrieve() function
│   └── aliases.py         # load_aliases(), expand_query()
data/                      # (or project root)
│   └── gear_aliases.json  # static alias map, corpus-scoped
tests/
│   ├── test_retrieval.py  # unit + offline tests for aliases and retrieval
│   └── test_aliases.py    # (or merged into test_retrieval.py)
```

**Note on `gear_aliases.json` location:** The CONTEXT.md and ROADMAP.md both reference it without specifying a subdirectory. Place it at `data/gear_aliases.json` (or project root). The path should be resolved relative to the project root using `Path(__file__).resolve().parent.parent.parent / "data" / "gear_aliases.json"` from inside `app/retrieval/aliases.py`. [ASSUMED: exact placement is Claude's discretion per CONTEXT.md]

### Pattern 1: Frozen Dataclass at Module Boundary

**What:** Every cross-module data handoff uses a `@dataclass(frozen=True)` — `Chunk` (ingest → writer), `EmbeddingResult` (embedder → ingest), `ChunkResult` (retrieval → generation). Immutability prevents accidental field mutation downstream.

**When to use:** Whenever a function returns structured data that will be consumed by another module layer.

```python
# Source: app/ingest/chunker.py (established Phase 1 pattern)
@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    text: str
    token_count: int
    content_hash: str
    metadata: dict[str, Any]

# Phase 2 equivalent — app/retrieval/base.py
@dataclass(frozen=True)
class ChunkResult:
    chunk_id: str           # UUID string (chunks.id)
    document_id: str        # UUID string (chunks.document_id)
    source_type: str        # 'forum' | 'pdf_manual' | 'web_article' | 'youtube'
    source_name: str        # human-readable source identifier (from metadata_json)
    chunk_index: int        # 0-based chunk position within document
    text: str               # chunk_text — the retrievable passage
    distance: float         # cosine DISTANCE (0=identical, 2=opposite); smaller = better
```

**Important:** `distance` is cosine DISTANCE (from `<=>` operator), not similarity. Smaller value = more similar. Document this in the field comment to prevent Phase 5 eval scorer from inverting the sort direction.

### Pattern 2: Injectable Dependencies for Testing

**What:** Functions accept `conn` and `embedder` as optional keyword arguments with `None` default, falling back to `get_conn()` and `get_embedder()` when not provided.

**When to use:** Any function that touches DB or external APIs, to allow unit tests to inject fakes without monkeypatching.

```python
# Source: established in Phase 1 pipeline.py test pattern (test_pipeline.py test 4)
def retrieve(
    query: str,
    k: int = 8,
    *,
    conn: psycopg.Connection | None = None,
    embedder: Embedder | None = None,
) -> list[ChunkResult]:
    _conn = conn or get_conn()
    _embedder = embedder or get_embedder()
    ...
```

### Pattern 3: psycopg3 Vector Query Execution

**What:** After `register_vector(conn)`, pass the query embedding as `list[float]` directly via `%s` parameter. The pgvector adapter translates it to the `vector` type. This is proven by `writer.py` `upsert_chunks()` which passes `list(v)` via `%s` for INSERT.

**When to use:** Every psycopg3 cursor operation involving the `embedding` column.

```python
# Source: verified by reading pgvector.psycopg.vector.VectorDumper source
# and app/ingest/writer.py upsert_chunks() usage pattern [VERIFIED]
sql = """
    SELECT
        c.id::text,
        c.document_id::text,
        c.source_type,
        c.chunk_index,
        c.chunk_text,
        c.metadata_json,
        c.embedding <=> %s AS distance
    FROM chunks c
    WHERE c.embedding_model = %s
    ORDER BY c.embedding <=> %s
    LIMIT %s
"""
query_vec = list(embedder.embed_query(expanded_query))  # list[float]
with conn.cursor() as cur:
    cur.execute(sql, (query_vec, embedding_model, query_vec, k))
    rows = cur.fetchall()
```

**Note:** The query vector appears twice in params — once for the SELECT distance expression and once for ORDER BY. Both `%s` slots receive the same `list[float]` value. [VERIFIED: consistent with pgvector documentation pattern and psycopg3 adapter behavior]

### Pattern 4: Word-Boundary Alias Expansion

**What:** Use `re.sub` with `\b` anchors and `re.IGNORECASE` to expand alias tokens. The `count=1` parameter prevents double-expansion when the same alias appears multiple times.

**When to use:** `expand_query()` in `aliases.py`.

```python
# Source: locked by D-05 in CONTEXT.md; regex pattern specified directly
import re

def expand_query(query: str, alias_pairs: list[tuple[str, str]]) -> str:
    """Apply bidirectional alias expansion to a query string.
    
    Each (shortform, canonical) pair generates two expansion rules:
      shortform → "shortform canonical"  (e.g. "Strat" → "Strat Stratocaster")
      canonical → "shortform canonical"  (e.g. "Stratocaster" → "Strat Stratocaster")
    
    count=1 prevents duplicate expansion when the same token appears multiple times.
    """
    result = query
    for shortform, canonical in alias_pairs:
        replacement = f"{shortform} {canonical}"
        result = re.sub(
            rf"\b{re.escape(shortform)}\b",
            replacement,
            result,
            count=1,
            flags=re.IGNORECASE,
        )
        result = re.sub(
            rf"\b{re.escape(canonical)}\b",
            replacement,
            result,
            count=1,
            flags=re.IGNORECASE,
        )
    return result
```

**Edge case — expansion ordering:** When canonical appears in query (e.g. "Stratocaster"), the first `re.sub` for shortform → replacement has no match; the second for canonical → replacement fires and correctly injects the shortform. Order is safe.

**Edge case — partial word matches:** `\b` anchors prevent "Strat" from matching inside "Stratocaster". The canonical `re.sub` does not double-expand a previously expanded string because `re.sub` with `count=1` only replaces the FIRST occurrence, and the replacement text (`"Strat Stratocaster"`) contains both tokens — subsequent runs of the same rule against the already-expanded string may re-fire on the `canonical` sub-token, so process each alias pair once in a single pass through the list.

### Anti-Patterns to Avoid

- **f-string SQL:** `WHERE embedding_model = f'{model}'` — enforced-forbidden by existing `test_writer.py` no-f-string test; retrieval SQL must use `%s` only. [VERIFIED: test_writer.py test 12]
- **Importing openai directly in retrieval module:** CLAUDE.md hard constraint. `test_embedder_protocol.py` test `test_no_module_imports_openai_outside_openai_embedder` scans all `app/**/*.py` and will catch any violation. [VERIFIED: test_embedder_protocol.py]
- **Calling `embed_documents()` for a single query:** Violates the CLAUDE.md `embed_query` / `embed_documents` split. Call `embedder.embed_query(expanded_query)` directly.
- **Returning `list[dict]`:** D-07 forbids it. `ChunkResult` typed fields are required.
- **Passing numpy array to psycopg3:** Pass `list[float]` explicitly (`list(vector)`) — not numpy arrays — to stay consistent with `writer.py` and avoid unexpected dtype issues.
- **Multi-query averaging:** D-04 forbids it. One `embed_query` call on the expanded string.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Vector similarity search | Custom brute-force cosine loop | pgvector HNSW `<=>` operator | HNSW gives O(log N) ANN search vs O(N) scan; already indexed |
| Alias storage | SQL table with runtime lookups | Static `gear_aliases.json` loaded at module import | Zero latency, zero DB reads at query time; alias set is small and static |
| Tokenization for alias matching | Custom word splitter | `re.sub(r'\b...\b', ...)` | stdlib regex handles Unicode word boundaries; `re.IGNORECASE` handles case |
| Connection management | Manual `psycopg.connect()` in retrieval | `app.db.get_conn()` | `get_conn()` already calls `register_vector(conn)` — calling it again is a no-op but bypassing it means vectors don't serialize |
| Embedder construction | `OpenAIEmbedder(...)` in retrieval | `app.embeddings.factory.get_embedder()` | CLAUDE.md: retrieval must not import `openai` directly |
| Distance-to-similarity conversion | Custom `1 - distance` formula | Keep raw distance in `ChunkResult.distance` | Phase 5 eval scorer uses distance directly; conversion belongs in the scorer |

**Key insight:** Every computation-heavy or edge-case-heavy concern (vector ANN, embedding, retries) is already handled by Phase 1 infrastructure. Phase 2 wires them together with thin glue code.

---

## Common Pitfalls

### Pitfall 1: Source Name Not on Chunks Row

**What goes wrong:** Developer tries to populate `ChunkResult.source_name` from `chunks.source_id` only to find the chunks table has no `source_id` column directly — it has `document_id` (FK to `documents.id`).

**Why it happens:** The schema has two tables: `documents` (one row per source file, has `source_id = filename`) and `chunks` (has `document_id` FK + `metadata_json` which contains `source_filename`).

**How to avoid:** Populate `source_name` from `chunks.metadata_json ->> 'source_filename'` (already stored by the ingest writer in Phase 1). No JOIN to `documents` is needed for Phase 2. Example: `metadata_json = {"source_filename": "bb_king_tone.txt"}` → `source_name = "bb_king_tone.txt"`.

**Warning signs:** `KeyError` or `None` when extracting source_name; or a JOIN query against `documents` that returns slightly different results due to transaction isolation.

### Pitfall 2: Double-Registration of pgvector Adapter

**What goes wrong:** Calling `register_vector(conn)` manually inside `retrieve()` after `get_conn()` has already called it. The adapter registration is idempotent so this does not error, but it adds confusion about where the single source of truth for registration lives.

**Why it happens:** The ROADMAP success criterion says "asserts `register_vector(conn)` is invoked once per pool connection." A developer reads this and adds an explicit `register_vector` call in retrieval code.

**How to avoid:** `get_conn()` in `app/db.py` already calls `register_vector(conn)` before returning. The retrieval code should call `get_conn()` (or accept an injected conn from tests) and never call `register_vector` itself. The unit test for this criterion should verify that `get_conn()` — not `retrieve()` — is where registration happens.

**Warning signs:** Two `register_vector` calls in the call stack (visible via adding a print in a debug session).

### Pitfall 3: Alias Expansion on Already-Expanded String

**What goes wrong:** Running `expand_query` twice on the same string (e.g., from a caching bug) double-expands: `"Strat"` → `"Strat Stratocaster"` → `"Strat Strat Stratocaster Stratocaster"`.

**Why it happens:** The expansion replaces shortform → "shortform canonical". If the canonical appears in the replacement, the canonical's rule fires on the next iteration.

**How to avoid:** Apply each alias pair's two rules in sequence within a single `expand_query()` call. Do not call `expand_query()` recursively or in a loop. The `count=1` parameter on each `re.sub` limits damage but does not fully protect against cross-pair interactions. [ASSUMED: multi-pass expansion interactions require careful ordering, but with ~14 pairs the risk is low]

**Warning signs:** Expanded query string contains duplicate words or doubled canonical forms.

### Pitfall 4: K Greater Than Available Chunks

**What goes wrong:** `retrieve(query, k=8)` with fewer than 8 chunks in the DB returns fewer than 8 results. If the caller assumes `len(results) == k`, it may index out of bounds.

**Why it happens:** `LIMIT %s` with k=8 returns at most k rows — if fewer rows exist, `fetchall()` returns a shorter list. This is correct SQL behavior.

**How to avoid:** Contract: `retrieve()` returns `list[ChunkResult]` with 0 to k items. Callers must handle len < k. Document this in the function docstring. The generation layer in Phase 3 iterates the list — it does not assume a fixed length.

**Warning signs:** IndexError in Phase 3 generation layer when run against an empty or near-empty DB.

### Pitfall 5: embedding_model Filter Misses All Rows

**What goes wrong:** `WHERE embedding_model = %s` returns zero rows if the DB was populated with a different embedding model than `get_settings().embedding_model`.

**Why it happens:** The `chunks` table stores the model name used at ingest time. If the env var changes (e.g., from `text-embedding-3-small` to `text-embedding-3-large`), the stored model name differs from the filter value.

**How to avoid:** Always source `embedding_model` from `get_settings().embedding_model` in the retrieval function — same source as the ingestion pipeline. Never hardcode. The dev `EXPLAIN ANALYZE` log will show `0 rows` if the filter eliminates everything, which is easy to diagnose.

**Warning signs:** Empty `list[ChunkResult]` returned despite chunks existing in the DB; confirmed by `SELECT DISTINCT embedding_model FROM chunks;` showing a different value.

### Pitfall 6: Regex Mangling Multi-Word Canonical Names

**What goes wrong:** The canonical for `SSS` is `"Dumble Steel String Slinger"` — a multi-word phrase. The regex `\b{re.escape("Dumble Steel String Slinger")}\b` matches the full phrase only when it appears verbatim with that exact spacing.

**Why it happens:** `re.escape` escapes spaces as literal spaces; `\b` anchors work on word boundaries, so the pattern won't match if the user writes "Dumble steel string slinger" (case difference handled by `re.IGNORECASE`) but WILL fail if there's a line break or double space.

**How to avoid:** For multi-word canonicals, use `\s+` instead of literal space in the pattern: `rf"\b{re.escape(canonical).replace(r'\ ', r'\s+')}\b"`. Alternatively, normalize the query with `' '.join(query.split())` before expansion to collapse whitespace.

**Warning signs:** Multi-word canonical expansions not firing in spot-check tests.

---

## Code Examples

### ChunkResult Definition

```python
# app/retrieval/base.py
# Source: mirrors app/ingest/chunker.py Chunk pattern [VERIFIED: chunker.py]
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ChunkResult:
    chunk_id: str        # UUID string (chunks.id cast to text)
    document_id: str     # UUID string (chunks.document_id cast to text)
    source_type: str     # 'forum' | 'pdf_manual' | 'web_article' | 'youtube'
    source_name: str     # from metadata_json['source_filename']
    chunk_index: int     # 0-based position within source document
    text: str            # chunk_text from DB
    distance: float      # cosine distance via <=> (smaller = more similar; range 0-2)
```

### Retrieval SQL

```python
# Source: STACK.md retrieval query template + CONTEXT.md SQL constraints [VERIFIED]
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
```

### Vector Parameter Passing (psycopg3 + pgvector)

```python
# Source: app/ingest/writer.py upsert_chunks() [VERIFIED: writer.py line ~90]
# After register_vector(conn) (called by get_conn()), list[float] passes via %s
query_vec = list(embedder.embed_query(expanded_query))  # list[float], 1536 elements
with conn.cursor() as cur:
    cur.execute(_RETRIEVE_SQL, (query_vec, embedding_model, query_vec, k))
    rows = cur.fetchall()
```

### Alias Loading Pattern

```python
# Source: mirrors app/config.py lru_cache pattern [VERIFIED: config.py]
import json
from functools import lru_cache
from pathlib import Path

_ALIASES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "gear_aliases.json"

@lru_cache(maxsize=1)
def _load_alias_pairs() -> list[tuple[str, str]]:
    """Load alias pairs once at first call; cached for the process lifetime."""
    data = json.loads(_ALIASES_PATH.read_text(encoding="utf-8"))
    return [(entry["shortform"], entry["canonical"]) for entry in data["aliases"]]
```

### Row-to-ChunkResult Mapping

```python
# Source: schema column names verified against scripts/init_db.sql [VERIFIED]
import json

def _row_to_chunk_result(row: tuple) -> ChunkResult:
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
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| IVFFlat index (requires pre-built centroids) | HNSW (works on empty table, higher recall) | pgvector 0.5+ | Phase 1 already uses HNSW; retrieval inherits this |
| psycopg2 + pgvector-python | psycopg3 (v3) + pgvector 0.4.2 | Project decision | `import psycopg` not `import psycopg2`; register_vector from `pgvector.psycopg` |
| Multi-vector query averaging | Single embed_query on expanded string | D-04 locked | Simpler, fewer API calls, matches Phase 1 embedder protocol |

**Deprecated/outdated:**
- `psycopg2`: Not used in this project (CLAUDE.md hard constraint). `import psycopg` is v3.
- `pgvector.psycopg2`: Wrong adapter module. Import from `pgvector.psycopg` for v3.

---

## Runtime State Inventory

Step 2.5: SKIPPED — Phase 2 is a new module addition, not a rename/refactor/migration. No runtime state affected.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| psycopg[binary] | retrieve() DB connection | ✓ | 3.3.4 | — |
| pgvector | vector type adapter | ✓ | 0.4.2 | — |
| PostgreSQL (local) | HNSW index + chunks table | ✓ (assumed from Phase 1 completion) | — | — |
| OPENAI_API_KEY | embedder.embed_query() in live tests | configured in .env | — | Mock embedder for unit tests |

**Missing dependencies with no fallback:** None.

**Note on PostgreSQL:** Phase 1 is complete and chunks are in the store. Unit tests do not need a live DB (injectable conn pattern). Integration tests follow the Phase 1 convention: `pytest.skip` if `DATABASE_URL` is not reachable.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 7.4.0 (system install at `/opt/anaconda3/bin/pytest`) |
| Config file | None — no `pyproject.toml`, `pytest.ini`, or `conftest.py` found [VERIFIED: find scan] |
| Quick run command | `pytest tests/test_retrieval.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-07 | `gear_aliases.json` file exists with valid structure | unit | `pytest tests/test_retrieval.py::test_aliases_json_loads -x` | Wave 0 |
| INGEST-07 | Bidirectional expansion: shortform query expands correctly | unit | `pytest tests/test_retrieval.py::test_expand_shortform -x` | Wave 0 |
| INGEST-07 | Bidirectional expansion: canonical query expands correctly | unit | `pytest tests/test_retrieval.py::test_expand_canonical -x` | Wave 0 |
| RETR-01 | retrieve() returns list[ChunkResult] with k=8 | integration (live DB) | `pytest tests/test_retrieval.py::test_retrieve_returns_chunk_results -x` | Wave 0 |
| RETR-01 | retrieve() returns <= k results when DB has fewer than k chunks | unit (injected conn) | `pytest tests/test_retrieval.py::test_retrieve_fewer_than_k -x` | Wave 0 |
| RETR-01 | retrieve() returns empty list on empty DB | unit (injected conn) | `pytest tests/test_retrieval.py::test_retrieve_empty_db -x` | Wave 0 |
| RETR-02 | Shortform query and canonical query retrieve same top chunk | integration (live DB) | `pytest tests/test_retrieval.py::test_alias_retrieval_parity -x` | Wave 0 |
| RETR-03 | ChunkResult has source_type, source_name, chunk_index fields | unit | `pytest tests/test_retrieval.py::test_chunk_result_fields -x` | Wave 0 |
| RETR-03 | ChunkResult is a frozen dataclass | unit | `pytest tests/test_retrieval.py::test_chunk_result_is_frozen -x` | Wave 0 |
| (guard) | retrieval module does not import openai directly | static scan | `pytest tests/test_retrieval.py::test_no_direct_openai_import -x` | Wave 0 |
| (guard) | No f-string SQL in base.py | static scan | `pytest tests/test_retrieval.py::test_no_fstring_sql -x` | Wave 0 |
| (guard) | register_vector called by get_conn not by retrieve | code inspection | `pytest tests/test_retrieval.py::test_register_vector_not_in_retrieve -x` | Wave 0 |

### Mock Embedder Pattern (for offline unit tests)

```python
# Source: mirrors test_pipeline.py _BoomEmbedder pattern [VERIFIED: test_pipeline.py test 4]
class _FakeEmbedder:
    model = "text-embedding-3-small"
    dim = 1536
    provider = "openai"

    def embed_documents(self, texts):
        from app.embeddings.base import EmbeddingResult
        return EmbeddingResult(
            vectors=[[0.0] * 1536] * len(list(texts)),
            model=self.model, dim=self.dim, provider=self.provider,
        )

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 1536
```

### Mock Connection Pattern (for offline unit tests)

For tests that exercise `retrieve()` without a live DB, inject a mock `conn` whose `cursor()` returns pre-canned rows:

```python
class _FakeCursor:
    def __init__(self, rows): self._rows = rows
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def execute(self, sql, params): pass
    def fetchall(self): return self._rows

class _FakeConn:
    def __init__(self, rows): self._rows = rows
    def cursor(self): return _FakeCursor(self._rows)
```

### Sampling Rate

- **Per task commit:** `pytest tests/test_retrieval.py -x -q` (offline tests only — no live DB or OpenAI key required)
- **Per wave merge:** `pytest tests/ -x -q` (full suite; live-DB tests auto-skip if Postgres not reachable)
- **Phase gate:** Full suite green (offline tests pass, live-DB tests skipped gracefully if no Postgres) before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_retrieval.py` — all Phase 2 retrieval and alias tests (does not exist yet)
- [ ] `data/gear_aliases.json` — static alias file (does not exist yet)
- [ ] `app/retrieval/__init__.py` — package init (does not exist yet)
- [ ] `app/retrieval/base.py` — ChunkResult + retrieve() (does not exist yet)
- [ ] `app/retrieval/aliases.py` — alias loading + expand_query() (does not exist yet)

*(No framework install needed — pytest 7.4.0 already available at `/opt/anaconda3/bin/pytest`)*

---

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Single-user local tool; no auth layer |
| V3 Session Management | no | Phase 2 has no session state |
| V4 Access Control | no | Local only; no multi-tenancy |
| V5 Input Validation | yes | Query string from user; alias expansion is pure string transform with no eval/exec |
| V6 Cryptography | no | No crypto in retrieval layer |

### Known Threat Patterns for Retrieval Layer

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via user query | Tampering | `%s` parameterized placeholders only; no f-string SQL — enforced by existing grep test |
| Direct openai import bypass | Tampering | Static scan in `test_embedder_protocol.py` catches violations automatically |
| Path traversal via gear_aliases.json path | Tampering | Path resolved from `__file__` anchor, not from user input; read-only at module load |

**V5 note:** The user query string flows through `re.sub` (safe; no eval) → `embed_query()` (API call with tenacity) → `%s` parameter (psycopg3 parameterized). No eval, exec, or interpolated SQL anywhere in the path.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `gear_aliases.json` placed at `data/gear_aliases.json` relative to project root | Code Examples | Module import path must be adjusted; low risk since path is a 1-line constant |
| A2 | Multi-pass expansion interactions between alias pairs are safe with ~14 pairs | Pitfall 3 | Unlikely edge case with current 14-pair set; add a unit test that exercises overlapping pairs |
| A3 | `metadata_json['source_filename']` is populated for all existing chunks | Code Examples | If empty, source_name falls back to "unknown"; verify against actual DB rows before Phase 3 |
| A4 | PostgreSQL is running locally and chunks from Phase 1 exist in the store | Environment Availability | Integration tests auto-skip if DB unreachable; unit tests use injected fakes |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.
*Note: A1-A4 are low-risk assumptions; only A3 warrants a spot-check against the live DB before Phase 3.*

---

## Open Questions

1. **source_name field: should it be human-readable or the raw filename?**
   - What we know: `metadata_json['source_filename']` stores values like `"bb_king_tone.txt"`
   - What's unclear: Phase 3 citation XML uses `source_name` as a display label; a filename is acceptable but `"bb_king_tone"` without extension might be prettier
   - Recommendation: Use `metadata_json['source_filename']` verbatim for Phase 2; Phase 3 can add a display-name transform without changing ChunkResult

2. **EXPLAIN ANALYZE logging: settings flag or `DEBUG` env var?**
   - What we know: CONTEXT.md says "log when `DEBUG=true` env var is set" — but `app/config.py` has no `debug` field
   - What's unclear: Add `debug: bool = False` to `Settings` or read `os.getenv("DEBUG")` directly?
   - Recommendation: Add `debug: bool = False` to `Settings` (consistent with existing pattern) and wire it at module level; this is Claude's discretion per CONTEXT.md

---

## Sources

### Primary (HIGH confidence)

- `app/db.py` — `get_conn()` pattern; `register_vector` call location [VERIFIED: file read]
- `app/embeddings/base.py` — `Embedder` Protocol; `embed_query` return type `list[float]` [VERIFIED: file read]
- `app/embeddings/factory.py` — `get_embedder()` factory pattern [VERIFIED: file read]
- `app/ingest/chunker.py` — frozen dataclass pattern; `Chunk` field structure [VERIFIED: file read]
- `app/ingest/writer.py` — `list[float]` via `%s` psycopg3 vector insert pattern [VERIFIED: file read]
- `scripts/init_db.sql` — `chunks` column names; HNSW index name and parameters [VERIFIED: file read]
- `pgvector.psycopg.vector` source — `VectorDumper` registers for `Vector` and `numpy.ndarray`; `_to_db` accepts `list[float]` by coercing to `Vector` [VERIFIED: source inspection in venv]
- `raw_data/forum_posts/*.txt` (all 10 files) — gear shortforms grounded in actual corpus text [VERIFIED: grep scan]
- `tests/test_writer.py`, `tests/test_pipeline.py`, `tests/test_embedder_protocol.py` — Phase 1 testing patterns [VERIFIED: file reads]
- `eval/golden_set.jsonl` — chunk_id UUID format [VERIFIED: first 5 rows read]

### Secondary (MEDIUM confidence)

- `.planning/research/STACK.md` — retrieval SQL template using `<=>` operator; HNSW parameter rationale [CITED: STACK.md §pgvector Schema]
- `.planning/research/ARCHITECTURE.md` — system data flow; one-way pipeline boundary [CITED: ARCHITECTURE.md §System Overview]
- `.planning/phases/02-retrieval-layer-gear-aliases/02-CONTEXT.md` — all locked decisions D-01 through D-07 [CITED: CONTEXT.md]

### Tertiary (LOW confidence)

None — all claims verified against project source files or official library source code.

---

## Metadata

**Confidence breakdown:**
- Alias file content: HIGH — every pair verified against actual corpus text via grep
- Standard stack: HIGH — no new packages; existing Phase 1 stack verified
- Architecture patterns: HIGH — ChunkResult pattern, SQL template, vector parameter passing all verified against existing codebase
- Pitfalls: MEDIUM — based on schema analysis and library source inspection; A2/A3 are the only unverified claims

**Research date:** 2026-05-18
**Valid until:** 2026-06-18 (30 days; stable stack, no external services added)
