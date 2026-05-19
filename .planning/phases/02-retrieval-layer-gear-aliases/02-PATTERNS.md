# Phase 2: Retrieval Layer & Gear Aliases - Pattern Map

**Mapped:** 2026-05-18
**Files analyzed:** 5 (3 new Python modules, 1 JSON data file, 1 test module)
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `app/retrieval/__init__.py` | package-init | — | `app/embeddings/__init__.py` | exact |
| `app/retrieval/base.py` | service + model | request-response (CRUD-read) | `app/ingest/writer.py` + `app/embeddings/base.py` | role-match (read vs write) |
| `app/retrieval/aliases.py` | utility | transform | `app/embeddings/factory.py` + `app/config.py` | role-match |
| `data/gear_aliases.json` | config | — | none (new static data file) | no-analog |
| `tests/test_retrieval.py` | test | — | `tests/test_writer.py` + `tests/test_pipeline.py` | exact |

---

## Pattern Assignments

### `app/retrieval/__init__.py` (package-init)

**Analog:** `app/embeddings/__init__.py` and `app/ingest/__init__.py`

Both existing package `__init__.py` files are empty (a single blank line). Follow the same convention: create the file with no content. Do not add re-exports here; `base.py` and `aliases.py` are imported directly by callers.

**Pattern — empty init** (analog: `app/embeddings/__init__.py`, entire file):
```python
# (empty — package marker only)
```

---

### `app/retrieval/base.py` (service + model, request-response)

**Analogs:**
- `app/embeddings/base.py` — frozen dataclass + Protocol pattern (lines 1–62)
- `app/ingest/chunker.py` — `Chunk` frozen dataclass field structure (lines 57–82)
- `app/ingest/writer.py` — psycopg3 cursor pattern, `%s` placeholders, `list(v)` vector passing (lines 1–30, 70–81, 171–203)
- `app/db.py` — `get_conn()` as the only connection path (lines 27–37)

**Imports pattern** (mirror `app/ingest/writer.py` lines 25–31, `app/embeddings/base.py` lines 18–21):
```python
from __future__ import annotations

import json
from dataclasses import dataclass

import psycopg

from app.config import get_settings
from app.db import get_conn
from app.embeddings.base import Embedder
from app.embeddings.factory import get_embedder
from app.retrieval.aliases import expand_query
```

**ChunkResult frozen dataclass** (mirror `app/ingest/chunker.py` lines 57–82, `app/embeddings/base.py` lines 24–39):
```python
@dataclass(frozen=True)
class ChunkResult:
    """One retrieved chunk with full source metadata.

    Attributes:
        chunk_id:    UUID string (chunks.id cast to text).
        document_id: UUID string (chunks.document_id cast to text).
        source_type: 'forum' | 'pdf_manual' | 'web_article' | 'youtube'.
        source_name: Human-readable source — from metadata_json['source_filename'].
        chunk_index: 0-based position within the parent document.
        text:        chunk_text from DB — the retrievable passage.
        distance:    Cosine DISTANCE via <=> operator (range 0–2).
                     Smaller = more similar. NOT cosine similarity.
    """

    chunk_id: str
    document_id: str
    source_type: str
    source_name: str
    chunk_index: int
    text: str
    distance: float
```

**Core retrieval SQL constant** (no f-strings — enforced by test gate; mirror `app/ingest/writer.py` lines 173–185):
```python
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

**Injectable dependency signature** (mirror `app/ingest/pipeline.py` + `test_pipeline.py` injectable pattern):
```python
def retrieve(
    query: str,
    k: int = 8,
    *,
    conn: psycopg.Connection | None = None,
    embedder: Embedder | None = None,
) -> list[ChunkResult]:
```

**psycopg3 cursor execution pattern** (mirror `app/ingest/writer.py` lines 70–81, 200–202):
```python
    _conn = conn or get_conn()
    _embedder = embedder or get_embedder()
    embedding_model = get_settings().embedding_model

    expanded = expand_query(query)
    query_vec = list(_embedder.embed_query(expanded))  # list[float]; list() per writer.py convention

    with _conn.cursor() as cur:
        cur.execute(_RETRIEVE_SQL, (query_vec, embedding_model, query_vec, k))
        rows = cur.fetchall()
```

**Row-to-dataclass mapping** (mirror `app/ingest/writer.py` json.loads pattern, lines 196–199):
```python
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

**No-f-string constraint** — `app/ingest/writer.py` module docstring lines 20–22 states the rule; `tests/test_writer.py` lines 453–505 enforce it via regex scan. The identical scan will be reproduced in `tests/test_retrieval.py` targeting `app/retrieval/base.py`.

**No direct `openai` import** — `tests/test_embedder_protocol.py` lines 129–152 scan `app/**/*.py` and will catch any violation in `app/retrieval/`. Do not import `openai`, `openai_embedder`, or any OpenAI SDK symbol directly — route through the `Embedder` Protocol via `get_embedder()`.

**`register_vector` must NOT be called inside `retrieve()`** — `app/db.py` lines 35–36 show `get_conn()` already calls `register_vector(conn)` before returning. Retrieval code must not call it again. This is verified by a static test (see `tests/test_retrieval.py` pattern below).

---

### `app/retrieval/aliases.py` (utility, transform)

**Analogs:**
- `app/embeddings/factory.py` — module-level function dispatching on settings (lines 1–51)
- `app/config.py` — `@lru_cache(maxsize=1)` singleton loader pattern (lines 41–45)
- `app/db.py` — `Path(__file__).resolve().parent.parent` anchor for project-relative paths (line 24)

**Imports pattern** (mirror `app/config.py` lines 13–16, `app/db.py` lines 14–16):
```python
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
```

**Path anchor for data file** (mirror `app/db.py` line 24 two-parent-hop pattern):
```python
# app/retrieval/aliases.py is at <root>/app/retrieval/aliases.py
# Three .parent hops: aliases.py → retrieval/ → app/ → <root>
_ALIASES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "gear_aliases.json"
```

**`lru_cache` loader** (mirror `app/config.py` lines 41–45 `get_settings` pattern):
```python
@lru_cache(maxsize=1)
def _load_alias_pairs() -> list[tuple[str, str]]:
    """Load alias pairs once at first call; cached for process lifetime.

    Tests that need to override aliases must call _load_alias_pairs.cache_clear()
    — same convention as get_settings.cache_clear() in test_embedder_protocol.py.
    """
    data = json.loads(_ALIASES_PATH.read_text(encoding="utf-8"))
    return [(entry["shortform"], entry["canonical"]) for entry in data["aliases"]]
```

**`expand_query` public function** (pattern locked by D-03/D-05 in CONTEXT.md):
```python
def expand_query(query: str, alias_pairs: list[tuple[str, str]] | None = None) -> str:
    """Apply bidirectional alias expansion to a query string.

    Uses word-boundary matching (\\b) so 'Strat' does not expand inside
    'Stratocaster'. Case-insensitive. count=1 prevents duplicate expansion
    when the same token appears multiple times.

    Args:
        query:       Raw user query string.
        alias_pairs: Override for testing; defaults to _load_alias_pairs().

    Returns:
        Expanded query string with shortform and canonical forms both present.
    """
    pairs = alias_pairs if alias_pairs is not None else _load_alias_pairs()
    result = query
    for shortform, canonical in pairs:
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

---

### `data/gear_aliases.json` (static config)

**No codebase analog** — first static JSON data file in the project. Structure is specified by RESEARCH.md and grounded in the forum corpus scan.

**JSON schema** (14 corpus-verified pairs from RESEARCH.md §Alias File):
```json
{
  "aliases": [
    {"shortform": "Strat",     "canonical": "Stratocaster"},
    {"shortform": "Tele",      "canonical": "Telecaster"},
    {"shortform": "EVH",       "canonical": "Eddie Van Halen"},
    {"shortform": "SLO",       "canonical": "Soldano SLO-100"},
    {"shortform": "5150",      "canonical": "Peavey 5150"},
    {"shortform": "6505",      "canonical": "Peavey 6505"},
    {"shortform": "AX8",       "canonical": "Fractal AX8"},
    {"shortform": "SD1",       "canonical": "Boss SD-1"},
    {"shortform": "GE-7",      "canonical": "Boss GE-7"},
    {"shortform": "HM-2",      "canonical": "Boss HM-2"},
    {"shortform": "Dual Rec",  "canonical": "Mesa Dual Rectifier"},
    {"shortform": "Maxon 808", "canonical": "Maxon OD808"},
    {"shortform": "SRV",       "canonical": "Stevie Ray Vaughan"},
    {"shortform": "SSS",       "canonical": "Dumble Steel String Slinger"}
  ]
}
```

Every entry is traceable to actual text in `raw_data/forum_posts/*.txt` (verified by RESEARCH.md grep scan). Do NOT add entries not found in the corpus.

---

### `tests/test_retrieval.py` (test)

**Analogs:**
- `tests/test_writer.py` — DB-gated fixture pattern, `_make_*` factory helpers, static-scan test (lines 33–115, 453–505)
- `tests/test_pipeline.py` — `_BoomEmbedder` injectable fake pattern, `monkeypatch`-based override (lines 174–198)
- `tests/test_embedder_protocol.py` — `lru_cache.cache_clear()` in autouse fixture, static `rglob` scan (lines 32–44, 129–152)

**Module-level imports pattern** (mirror `test_writer.py` lines 13–24):
```python
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.retrieval.base import ChunkResult
```

**DB-gated fixture** (mirror `test_writer.py` lines 33–58 exactly — same skip convention):
```python
@pytest.fixture(scope="module")
def db_conn():
    """Live Postgres connection + schema bootstrap. Skip if unreachable."""
    try:
        from app.db import get_conn, init_schema
    except Exception as e:
        pytest.skip(f"app.db import failed: {e!r}")
    try:
        conn = get_conn()
    except Exception as e:
        pytest.skip(f"Postgres not reachable: {e!r}")
    try:
        init_schema(conn)
    except Exception as e:
        conn.close()
        pytest.skip(f"init_schema failed: {e!r}")
    yield conn
    conn.close()
```

**Table cleanup autouse fixture** (mirror `test_writer.py` lines 61–79):
```python
@pytest.fixture(autouse=True)
def _clean_tables(request, db_conn):
    if "db_conn" not in request.fixturenames:
        yield
        return
    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE chunks, documents, ingest_runs CASCADE")
    db_conn.commit()
    yield
```

**`lru_cache` reset fixture for alias tests** (mirror `test_embedder_protocol.py` lines 32–44):
```python
@pytest.fixture(autouse=True)
def _reset_alias_cache():
    from app.retrieval.aliases import _load_alias_pairs
    _load_alias_pairs.cache_clear()
    yield
    _load_alias_pairs.cache_clear()
```

**Fake embedder** (mirror `test_pipeline.py` `_BoomEmbedder`, lines 175–189; adapted for retrieval):
```python
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

**Fake connection/cursor** (offline DB injection pattern — no analog, specified by RESEARCH.md §Mock Connection Pattern):
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

**Static scan — no f-string SQL** (mirror `test_writer.py` lines 453–505, target changed to `base.py`):
```python
def test_no_fstring_sql_in_base():
    base_path = Path(__file__).resolve().parent.parent / "app" / "retrieval" / "base.py"
    assert base_path.exists()
    contents = base_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"""f["'][^"']*\{[^"']*(SELECT|INSERT|UPDATE|DELETE|TRUNCATE)[^"']*["']""",
        re.IGNORECASE,
    )
    offenders = [line for line in contents.splitlines() if pattern.search(line)]
    assert offenders == [], f"f-string SQL in base.py: {offenders}"
```

**Static scan — no direct openai import** (mirror `test_embedder_protocol.py` lines 129–152, scoped to `app/retrieval/`):
```python
def test_no_direct_openai_import():
    retrieval_dir = Path(__file__).resolve().parent.parent / "app" / "retrieval"
    pattern = re.compile(r"^(from openai\b|import openai\b)", re.MULTILINE)
    violators = [
        str(f) for f in retrieval_dir.rglob("*.py")
        if pattern.search(f.read_text(encoding="utf-8"))
    ]
    assert violators == [], f"Direct openai import in retrieval/: {violators}"
```

**Static scan — `register_vector` not called inside `retrieve()`** (new pattern; no direct analog):
```python
def test_register_vector_not_in_retrieve():
    """get_conn() calls register_vector; retrieve() must not call it again."""
    base_path = Path(__file__).resolve().parent.parent / "app" / "retrieval" / "base.py"
    contents = base_path.read_text(encoding="utf-8")
    assert "register_vector" not in contents, (
        "register_vector must be called by get_conn(), not by retrieve(). "
        "See app/db.py lines 35-36."
    )
```

**Unit test structure** (mirror `test_writer.py` naming — numbered with descriptive names):
```python
# --- offline unit tests (no DB, no API key) ---
def test_aliases_json_loads(): ...
def test_expand_shortform(): ...
def test_expand_canonical(): ...
def test_chunk_result_fields(): ...
def test_chunk_result_is_frozen(): ...
def test_retrieve_fewer_than_k(): ...   # uses _FakeConn + _FakeEmbedder
def test_retrieve_empty_db(): ...       # uses _FakeConn returning []
def test_no_fstring_sql_in_base(): ...
def test_no_direct_openai_import(): ...
def test_register_vector_not_in_retrieve(): ...

# --- live-DB integration tests (gated by db_conn fixture) ---
def test_retrieve_returns_chunk_results(db_conn): ...
def test_alias_retrieval_parity(db_conn): ...
```

---

## Shared Patterns

### psycopg3 `%s` Parameterized SQL

**Source:** `app/ingest/writer.py` (every SQL statement, lines 58–301)
**Enforced by:** `tests/test_writer.py` `test_no_fstring_sql_in_writer` (lines 453–505)
**Apply to:** `app/retrieval/base.py` `_RETRIEVE_SQL` constant and all `cur.execute()` calls

Rule: every SQL string is a module-level constant (`_RETRIEVE_SQL = """..."""`) or a local variable. No f-strings. No string concatenation. All dynamic values injected via `%s` in the params tuple passed to `cur.execute(sql, params)`.

### `list(vector)` for pgvector Parameters

**Source:** `app/ingest/writer.py` line 195 — `list(v)` passed as the embedding parameter
**Apply to:** `app/retrieval/base.py` — `list(_embedder.embed_query(expanded))` before passing to `cur.execute`

Rule: always coerce to `list[float]` explicitly. Do not pass numpy arrays or raw generator output.

### `get_conn()` as the Sole Connection Path

**Source:** `app/db.py` lines 27–37
**Apply to:** `app/retrieval/base.py` retrieve() fallback when `conn` is None

```python
# app/db.py lines 27–37
def get_conn() -> psycopg.Connection:
    conn = psycopg.connect(get_settings().database_url)
    register_vector(conn)
    return conn
```

Retrieval code calls `_conn = conn or get_conn()`. Never calls `psycopg.connect()` directly. Never calls `register_vector()` — that is `get_conn()`'s responsibility.

### `@lru_cache(maxsize=1)` Singleton Loader

**Source:** `app/config.py` lines 41–45 (`get_settings`)
**Apply to:** `app/retrieval/aliases.py` `_load_alias_pairs()`

```python
# app/config.py lines 41–45
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached)."""
    return Settings()
```

Tests that need to override the cache call `_load_alias_pairs.cache_clear()` — the same pattern `test_embedder_protocol.py` uses for `get_settings.cache_clear()` (lines 42–44).

### Frozen Dataclass at Module Boundary

**Source:** `app/embeddings/base.py` lines 24–39 (`EmbeddingResult`); `app/ingest/chunker.py` lines 57–82 (`Chunk`)
**Apply to:** `app/retrieval/base.py` `ChunkResult`

Both existing boundary dataclasses use `@dataclass(frozen=True)` with typed fields and no methods. `ChunkResult` follows the same convention. Immutability prevents the Phase 3 generation layer from accidentally mutating retrieved results.

### Injectable Dependencies for Testing

**Source:** `tests/test_pipeline.py` lines 175–189 (`_BoomEmbedder` + `monkeypatch.setattr`)
**Apply to:** `app/retrieval/base.py` retrieve() signature; `tests/test_retrieval.py` fake objects

```python
# Pattern from test_pipeline.py lines 185–186
monkeypatch.setattr(pipeline, "get_embedder", lambda: _BoomEmbedder())
```

For retrieval tests, inject via keyword arguments instead of monkeypatching:
```python
retrieve(query, k=2, conn=_FakeConn(rows), embedder=_FakeEmbedder())
```

### `pytest.skip` for Infrastructure-Gated Tests

**Source:** `tests/test_writer.py` lines 40–58; `tests/test_pipeline.py` lines 33–54
**Apply to:** `tests/test_retrieval.py` `db_conn` fixture and any live-DB test

Pattern: wrap `get_conn()` in try/except inside a `scope="module"` fixture; call `pytest.skip(...)` on any exception. This keeps CI green when Postgres is not available.

### `from __future__ import annotations`

**Source:** All existing `app/` modules (lines 1 of `base.py`, `factory.py`, `writer.py`, `db.py`, `config.py`)
**Apply to:** `app/retrieval/base.py` and `app/retrieval/aliases.py` — first line of every new module.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `data/gear_aliases.json` | static config | — | First static JSON data file in the project; no existing JSON config files to mirror. Structure specified by RESEARCH.md §Bidirectionality Structure and locked by D-01/D-02. |

---

## Metadata

**Analog search scope:** `app/`, `tests/` (all Python files)
**Files scanned:** 15 source files read in full
**Analog selection rationale:**
- `app/retrieval/base.py` uses TWO analogs by design: `app/embeddings/base.py` for the frozen dataclass shape, and `app/ingest/writer.py` for the psycopg3 cursor execution pattern. Both are needed because the new file combines a data model with a DB-reading function.
- `app/retrieval/aliases.py` uses `app/config.py` for the `lru_cache` loader and `app/db.py` for the `Path(__file__).resolve().parent.parent` path anchor.
- `tests/test_retrieval.py` draws from two test files: `test_writer.py` for DB fixture + static-scan structure, and `test_pipeline.py` for the injectable fake embedder.

**Pattern extraction date:** 2026-05-18
