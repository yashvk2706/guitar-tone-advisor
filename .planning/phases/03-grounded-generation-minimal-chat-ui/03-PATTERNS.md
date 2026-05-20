# Phase 3: Grounded Generation & Minimal Chat UI - Pattern Map

**Mapped:** 2026-05-19
**Files analyzed:** 18 new/modified files
**Analogs found:** 14 / 18

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/generation/__init__.py` | package-init | — | `app/retrieval/__init__.py` | exact |
| `app/generation/prompt.py` | utility | transform | `app/retrieval/aliases.py` | role-match (pure-function module, stdlib-only) |
| `app/generation/generator.py` | service | streaming | `app/retrieval/base.py` (retrieve function) | partial-match (same injectable-dep pattern; data flow is novel) |
| `app/session.py` | service | event-driven | `app/retrieval/aliases.py` | partial-match (module-level state + lru_cache pattern) |
| `app/main.py` | controller | request-response | `app/ingest/pipeline.py` (main entry point) | partial-match (no FastAPI analog exists) |
| `app/config.py` (modify) | config | — | `app/config.py` itself | exact (add one field) |
| `tests/test_generation.py` | test | — | `tests/test_retrieval.py` | exact |
| `tests/test_session.py` | test | — | `tests/test_retrieval.py` | role-match |
| `tests/test_main.py` | test | — | `tests/test_retrieval.py` | role-match |
| `frontend/next.config.js` | config | — | none | no-analog |
| `frontend/app/layout.tsx` | component | — | none | no-analog |
| `frontend/app/page.tsx` | component | — | none | no-analog |
| `frontend/components/ChatPage.tsx` | component | request-response | none | no-analog |
| `frontend/components/MessageBubble.tsx` | component | — | none | no-analog |
| `frontend/components/CitationPill.tsx` | component | — | none | no-analog |
| `frontend/components/CitationDrawer.tsx` | component | request-response | none | no-analog |
| `frontend/components/CoverageIndicator.tsx` | component | — | none | no-analog |
| `frontend/hooks/useSSEStream.ts` | hook | streaming | none | no-analog (pattern fully specified in RESEARCH.md) |

---

## Pattern Assignments

### `app/generation/__init__.py` (package-init)

**Analog:** `app/retrieval/__init__.py`

**Core pattern** (entire file — 1 line):
```python
# empty — mirrors app/retrieval/__init__.py exactly
```

The file is intentionally empty. Logic lives in `prompt.py` and `generator.py`. Do not add imports or `__all__` here.

---

### `app/generation/prompt.py` (utility, transform)

**Analog:** `app/retrieval/aliases.py`

**Imports pattern** (`app/retrieval/aliases.py` lines 1–15):
```python
"""Module docstring describing what the module does and key constraints.

No external imports — stdlib only. This module must NEVER import ``openai``,
``psycopg``, or any non-stdlib package (CLAUDE.md constraint).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
```

For `prompt.py` the imports will be similarly minimal — no external deps:
```python
from __future__ import annotations

from app.retrieval.base import ChunkResult
```

**Module-level constant pattern** (`app/retrieval/aliases.py` lines 24–27 — path constant):
```python
_ALIASES_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "gear_aliases.json"
)
```
Apply same style for `SYSTEM_PROMPT_TEXT` — module-level string constant, ALL_CAPS name, placed above functions.

**Pure function signature pattern** (`app/retrieval/aliases.py` lines 46–49):
```python
def expand_query(
    query: str,
    alias_pairs: list[tuple[str, str]] | None = None,
) -> str:
```
Mirror this for `build_sources_xml(sources: list[ChunkResult]) -> str` and `build_messages(turns, user_message, sources) -> list[dict]` and `build_system_blocks() -> list[dict]`.

**Docstring pattern** (`app/retrieval/aliases.py` lines 46–79): Multi-line docstring with Args: and Returns: sections. Follow this style for all public functions.

**No external API calls** — `prompt.py` is pure transform; no DB, no embedder, no Anthropic SDK. Any function here must be offline-testable without mocks.

---

### `app/generation/generator.py` (service, streaming)

**Analog:** `app/retrieval/base.py` (retrieve function + ChunkResult)

**Imports pattern** (`app/retrieval/base.py` lines 18–31):
```python
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
```
For `generator.py` map to:
```python
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from sse_starlette.event import ServerSentEvent

from app.retrieval.base import ChunkResult
```

**Injectable-dependency signature pattern** (`app/retrieval/base.py` lines 116–128):
```python
def retrieve(
    query: str,
    k: int = 8,
    *,
    conn: psycopg.Connection | None = None,
    embedder: Embedder | None = None,
) -> list[ChunkResult]:
```
Mirror the keyword-only injection idiom for `stream_response`:
```python
async def stream_response(
    *,
    client: AsyncAnthropic,
    system_blocks: list[dict],
    messages: list[dict],
    sources: list[ChunkResult],
    session_id: str,
) -> AsyncIterator[ServerSentEvent]:
```
All injectable dependencies are keyword-only (after `*`). No default-to-None for `client` — tests must supply a fake explicitly.

**SQL constant pattern** (`app/retrieval/base.py` lines 69–82):
```python
_RETRIEVE_SQL = """
    SELECT
        c.id::text          AS chunk_id,
        ...
    FROM chunks c
    WHERE c.embedding_model = %s
    ORDER BY c.embedding <=> %s
    LIMIT %s
"""
```
The module-level `_CITATION_RE = re.compile(r'\[S(\d+)\]')` follows the same convention: private, ALL_CAPS suffix, placed above functions.

**Error handling pattern** (`app/ingest/pipeline.py` lines 156–179):
```python
    except Exception as e:
        try:
            conn.rollback()
        except Exception:  # pragma: no cover — best-effort cleanup
            pass
        # T-04-05: use repr(e) to avoid leaking traceback frames
        print(f"FAILED: {e!r}", file=sys.stderr)
        raise
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover — best-effort
            pass
```
For `generator.py`: exceptions from `client.messages.stream()` should propagate — do not swallow. The `async with` context manager handles stream cleanup automatically; no explicit `finally` needed on the stream itself.

---

### `app/session.py` (service, event-driven)

**Analog:** `app/retrieval/aliases.py` (module-level state + cached loader)

**Module-level state pattern** (`app/retrieval/aliases.py` lines 31–43):
```python
@lru_cache(maxsize=1)
def _load_alias_pairs() -> list[tuple[str, str]]:
    """Load alias pairs once at first call; cached for process lifetime.

    Tests that need to override aliases must call ``_load_alias_pairs.cache_clear()``
    """
    data = json.loads(_ALIASES_PATH.read_text(encoding="utf-8"))
    return [(entry["shortform"], entry["canonical"]) for entry in data["aliases"]]
```
For `session.py` the equivalent is a module-level `dict` (not lru_cache since it mutates):
```python
_sessions: dict[str, list[dict]] = {}
_lock = threading.Lock()
```
The docstring on `_load_alias_pairs` sets the test-cache-clear convention; follow the same pattern in docstrings for `get_or_create_session` explaining how tests reset state.

**Function docstring style** (`app/retrieval/aliases.py` lines 47–75):
```python
def expand_query(
    query: str,
    alias_pairs: list[tuple[str, str]] | None = None,
) -> str:
    """Apply bidirectional alias expansion to a query string.

    Each ``(shortform, canonical)`` pair generates two expansion rules:
    ...

    Args:
        query:       Raw user query string.
        alias_pairs: Override for testing; defaults to ``_load_alias_pairs()``.
                     Pass ``[]`` (empty list) to skip all expansion.

    Returns:
        Expanded query string with both shortform and canonical tokens present
        for any alias that matched.
    """
```
Apply to `get_or_create_session(session_id: str) -> dict` and `append_turn(session_id: str, role: str, content: str) -> None`.

---

### `app/main.py` (controller, request-response)

**Analog:** `app/ingest/pipeline.py` (closest entry-point pattern; no FastAPI analog exists)

**Module docstring pattern** (`app/ingest/pipeline.py` lines 1–29):
```python
"""Ingestion CLI — ``python -m app.ingest.pipeline``.

Wires together the loader → chunker → embedder → writer pipeline. ...

CLAUDE.md hard constraints honored here:
    - No direct ``openai`` import (only ``get_embedder()``).
    - All DB writes flow through ``app.ingest.writer`` (which uses ``%s``).
    - Source-type dispatch via ``chunk_document`` — no universal chunker.
"""
```
For `app/main.py`:
```python
"""FastAPI application — POST /chat, GET /sources/{chunk_id}, GET /health.

CLAUDE.md hard constraints:
    - No f-string SQL — GET /sources/{chunk_id} uses %s placeholders.
    - No direct openai import — retrieval routes through get_embedder().
    - register_vector() is called by get_conn(), not here.
"""
```

**SQL constant pattern** (`app/retrieval/base.py` lines 69–82 / `app/eval/author.py` lines 233–243):
```python
# app/eval/author.py — parametrized SQL with %s, no f-strings
sql = """
    SELECT
        c.id::text       AS chunk_id,
        c.chunk_text     AS chunk_text,
        c.metadata_json  AS metadata_json,
        d.source_id      AS source_filename
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    ORDER BY c.embedding <=> %s::vector
    LIMIT %s
"""
```
Place `_SOURCES_SQL` as a module-level constant above the route functions. Use exact column names from `scripts/init_db.sql`: `chunk_text`, `metadata_json`, `source_type`.

**DB connection pattern** (`app/db.py` lines 27–37 / `app/eval/author.py` lines 390–451):
```python
# Per-request connection (no pool in Phase 3)
conn = get_conn()
try:
    ...
finally:
    conn.close()
```
For `GET /sources/{chunk_id}`: use `get_conn()` per request. No pool. Match `app/eval/author.py`'s `try/finally conn.close()` pattern.

**Import pattern** (`app/ingest/pipeline.py` lines 32–51):
```python
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.db import get_conn
from app.embeddings.factory import get_embedder
from app.ingest.chunker import chunk_document
```
For `app/main.py`:
```python
from __future__ import annotations

import json
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sse_starlette.event import ServerSentEvent

from app.config import get_settings
from app.db import get_conn
from app.generation.generator import stream_response
from app.generation.prompt import build_messages, build_system_blocks
from app.retrieval.base import retrieve
from app.session import append_turn, get_or_create_session
```

---

### `app/config.py` (modify — add one field)

**Analog:** `app/config.py` itself

**Field addition pattern** (`app/config.py` lines 19–41):
```python
class Settings(BaseSettings):
    database_url: str = "postgresql://localhost:5432/guitar_tone_advisor"
    openai_api_key: str | None = None          # ← established pattern
    embedding_model: str = "text-embedding-3-small"
    debug: bool = False
```
Add `anthropic_api_key` immediately after `openai_api_key`, same pattern:
```python
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None       # ← add this line
```
Docstring comment: follow the inline comment style already present in the class docstring — add a bullet: `- ``anthropic_api_key`` is optional in tests; generation module refuses to construct AsyncAnthropic without it.`

**lru_cache singleton pattern** (`app/config.py` lines 44–48):
```python
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide ``Settings`` singleton (cached)."""
    return Settings()
```
Do not modify this function. Consumers call `get_settings().anthropic_api_key` — same as `get_settings().openai_api_key` in `app/embeddings/openai_embedder.py` line 53.

---

### `tests/test_generation.py` (test)

**Analog:** `tests/test_retrieval.py`

**Module docstring + coverage comment** (`tests/test_retrieval.py` lines 1–12):
```python
"""Retrieval layer tests — Phase 2.

Covers:
  - gear_aliases.json file structure (INGEST-07)
  - expand_query() bidirectional expansion (INGEST-07)
  - ChunkResult dataclass shape and immutability (RETR-03)
  - retrieve() with injected fake connection/embedder (RETR-01, RETR-02)
  - Static-scan guards: no f-string SQL, no direct openai import,
    register_vector not called inside retrieve() (CLAUDE.md constraints)

14 named tests total: 12 offline + 2 live-DB integration (skipped when Postgres unavailable).
"""
```

**Fake object pattern** (`tests/test_retrieval.py` lines 69–111):
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

class _FakeEmbedder:
    model = "text-embedding-3-small"
    dim = 1536
    provider = "openai"
    def embed_documents(self, texts): ...
    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 1536
```
For `test_generation.py`: create `_FakeAnthropicStream` and `_FakeAnthropicClient` fakes that yield pre-determined token sequences. Follow the same class-prefix `_Fake*` naming convention.

**autouse fixture pattern** (`tests/test_retrieval.py` lines 28–36):
```python
@pytest.fixture(autouse=True)
def _reset_alias_cache():
    from app.retrieval.aliases import _load_alias_pairs
    _load_alias_pairs.cache_clear()
    yield
    _load_alias_pairs.cache_clear()
```
For `test_generation.py` and `test_session.py`: add `autouse=True` fixture that clears `_sessions` dict in `app.session` between tests:
```python
@pytest.fixture(autouse=True)
def _reset_sessions():
    import app.session as s
    s._sessions.clear()
    yield
    s._sessions.clear()
```

**Static-scan guard pattern** (`tests/test_retrieval.py` lines 374–418):
```python
def test_no_fstring_sql_in_base():
    base_path = Path(__file__).resolve().parent.parent / "app" / "retrieval" / "base.py"
    contents = base_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"""f["'][^"']*\{[^"']*(SELECT|INSERT|UPDATE|DELETE|TRUNCATE)[^"']*["']""",
        re.IGNORECASE,
    )
    offenders = [line for line in contents.splitlines() if pattern.search(line)]
    assert offenders == [], f"f-string SQL found in base.py: {offenders}"

def test_no_direct_openai_import():
    retrieval_dir = Path(__file__).resolve().parent.parent / "app" / "retrieval"
    pattern = re.compile(r"^(from openai\b|import openai\b)", re.MULTILINE)
    violators = [
        str(f) for f in retrieval_dir.rglob("*.py")
        if pattern.search(f.read_text(encoding="utf-8"))
    ]
    assert violators == [], f"Direct openai import in retrieval/: {violators}"
```
For `test_main.py`: add `test_no_fstring_sql_in_main()` scanning `app/main.py` with the same regex pattern. For `test_generation.py`: add a test that `app/generation/` does not import `openai` directly.

**DB-gated fixture pattern** (`tests/test_retrieval.py` lines 44–61):
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
Apply same `scope="module"` + `pytest.skip(...)` pattern for `test_main.py`'s `GET /sources/{chunk_id}` integration test which requires a live Postgres.

**Import guard at top of test file** (`tests/test_embedder_protocol.py` lines 27–29):
```python
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```
Not needed if `pytest` is run from the project root with the venv activated (the existing test files omit this), but mirror if the file structure requires it.

---

### `tests/test_session.py` (test)

**Analog:** `tests/test_retrieval.py` — same framework, same conventions.

Apply the same patterns as `test_generation.py`:
- `_reset_sessions` autouse fixture (clear `_sessions` dict)
- `_reset_settings_cache` if settings are touched
- Offline-only tests (no DB needed for session store)
- Test naming: `test_<method>_<behavior>` pattern (e.g., `test_get_or_create_creates_new_session`)

---

### `tests/test_main.py` (test, integration)

**Analog:** `tests/test_retrieval.py` (live-DB gated fixture) + `starlette.testclient.TestClient` (no pytest-asyncio)

**TestClient pattern** (from RESEARCH.md, no existing analog — use starlette):
```python
from starlette.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
```
This replaces pytest-asyncio (not installed). `TestClient` wraps async routes synchronously — established by `starlette.testclient.TestClient` which is part of `fastapi`'s test utilities.

**db_conn fixture**: copy the `scope="module"` skip pattern from `tests/test_retrieval.py` lines 44–61 verbatim for the `GET /sources/{chunk_id}` integration test.

---

## Shared Patterns

### Settings Access (`get_settings()` singleton)

**Source:** `app/config.py` lines 44–48, consumed in `app/embeddings/openai_embedder.py` line 52–53
**Apply to:** `app/generation/generator.py`, `app/main.py`

```python
# Correct pattern — always import and call, never cache locally
from app.config import get_settings

api_key = get_settings().anthropic_api_key or "..."
```

Never call `os.getenv("ANTHROPIC_API_KEY")` directly. Always route through `get_settings()`.

### No f-string SQL

**Source:** `app/retrieval/base.py` lines 69–82 (SQL constant), `app/eval/author.py` lines 233–243
**Apply to:** `app/main.py` (`GET /sources/{chunk_id}` query), any DB access in `app/generation/generator.py`

```python
# Correct: module-level constant + %s placeholders
_SOURCES_SQL = """
    SELECT c.chunk_text, c.source_type, c.metadata_json, d.title
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE c.id = %s::uuid
"""

with conn.cursor() as cur:
    cur.execute(_SOURCES_SQL, (chunk_id,))
```

The static-scan test in `test_main.py` will enforce this.

### No Direct `openai` Import Outside `openai_embedder.py`

**Source:** `tests/test_embedder_protocol.py` lines 129–152
**Apply to:** `app/generation/` (must not import `openai`)

The existing `test_no_module_imports_openai_outside_openai_embedder` test scans all of `app/` — new generation files are automatically covered. Do not add `import openai` or `from openai` anywhere in `app/generation/`.

### `repr(e)` in Error Logging (not full traceback)

**Source:** `app/ingest/pipeline.py` lines 165–172
**Apply to:** `app/main.py` error handlers, `app/generation/generator.py`

```python
# Correct — avoids leaking SDK request bodies or API keys into logs
logger.error("Could not write fail_run audit row: %r (original: %r)", audit_err, e)
print(f"FAILED: {e!r}", file=sys.stderr)

# Wrong — may leak anthropic_api_key value in traceback
import traceback; traceback.format_exc()
```

### Injectable Dependencies for Testing

**Source:** `app/retrieval/base.py` lines 116–148 (keyword-only `conn=` and `embedder=` params)
**Apply to:** `app/generation/generator.py` (`client=` param), `app/main.py` (use FastAPI dependency injection or plain function param)

```python
# Pattern: all injectable deps are keyword-only, after *
def retrieve(
    query: str,
    k: int = 8,
    *,
    conn: psycopg.Connection | None = None,
    embedder: Embedder | None = None,
) -> list[ChunkResult]:
    _conn = conn or get_conn()
    _embedder = embedder or get_embedder()
```

For `stream_response`, the `client` is always required (no default) because there is no equivalent of `get_anthropic_client()` factory yet — tests must pass a fake.

### Frozen Dataclass at Module Boundary

**Source:** `app/retrieval/base.py` lines 38–63 (`ChunkResult`), `app/embeddings/base.py` lines 24–40 (`EmbeddingResult`)
**Apply to:** Any typed result struct exposed by `app/generation/`

```python
@dataclass(frozen=True)
class ChunkResult:
    chunk_id: str
    document_id: str
    source_type: str
    source_name: str
    chunk_index: int
    text: str
    distance: float
```

If `app/generation/` needs to expose a result type (e.g., `CitationResult`), follow this pattern: `@dataclass(frozen=True)`, all fields typed, placed near the top of the module before functions.

### `from __future__ import annotations`

**Source:** Every existing Python file in `app/` (lines 1)
**Apply to:** All new Python files

First line of every `app/*.py` and `app/**/*.py` file, before any other imports.

### Module-Level `logger = logging.getLogger(__name__)`

**Source:** `app/ingest/pipeline.py` line 51
**Apply to:** `app/main.py`, optionally `app/generation/generator.py`

```python
import logging
logger = logging.getLogger(__name__)
```

Use `logger.info(...)` / `logger.error(...)` not `print(...)` in `app/main.py` for request-handling events.

---

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md patterns and `03-UI-SPEC.md` as authoritative sources):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `frontend/next.config.js` | config | — | No Next.js code exists; pattern fully specified in RESEARCH.md §Code Examples |
| `frontend/app/layout.tsx` | component | — | No frontend code exists; use `03-UI-SPEC.md` |
| `frontend/app/page.tsx` | component | — | No frontend code exists; use `03-UI-SPEC.md` |
| `frontend/components/ChatPage.tsx` | component | request-response | No React components exist; use `03-UI-SPEC.md` |
| `frontend/components/MessageBubble.tsx` | component | — | No React components exist; use `03-UI-SPEC.md` |
| `frontend/components/CitationPill.tsx` | component | — | No React components exist; use `03-UI-SPEC.md` |
| `frontend/components/CitationDrawer.tsx` | component | request-response | No React components exist; use `03-UI-SPEC.md` |
| `frontend/components/CoverageIndicator.tsx` | component | — | No React components exist; use `03-UI-SPEC.md` |
| `frontend/hooks/useSSEStream.ts` | hook | streaming | No hooks exist; pattern fully specified in RESEARCH.md Pattern 6 |

**Note for planner:** All frontend patterns are derived from RESEARCH.md (HIGH confidence — verified against sse-starlette 3.4.4 wire format) and the approved `03-UI-SPEC.md` UI contract. RESEARCH.md Pattern 6 (`useSSEStream.ts`) is complete and copy-ready at lines 537–620.

---

## Metadata

**Analog search scope:** `app/`, `tests/`
**Files scanned:** 18 source files, 11 test files
**Pattern extraction date:** 2026-05-19
