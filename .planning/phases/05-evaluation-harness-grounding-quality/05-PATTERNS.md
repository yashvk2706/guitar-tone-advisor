# Phase 5: Evaluation Harness & Grounding Quality — Pattern Map

**Mapped:** 2026-05-28
**Files analyzed:** 6 (5 new Python files + 1 new data file)
**Analogs found:** 5 / 5 (data file has no code analog)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `app/eval/retrieval.py` | CLI script + utility | batch (DB read + file append) | `app/eval/author.py` | exact |
| `app/eval/ragas.py` | CLI script + utility | batch (DB read + Anthropic API) | `app/eval/author.py` + `app/generation/generator.py` | role-match |
| `tests/test_eval_retrieval.py` | test | batch (unit + integration) | `tests/test_retrieval.py` | exact |
| `tests/test_eval_refusal.py` | test | request-response (async generator) | `tests/test_generation.py` | exact |
| `tests/test_eval_ragas.py` | test | batch (unit + integration) | `tests/test_generation.py` + `tests/test_retrieval.py` | role-match |
| `eval/runs.jsonl` | data file | append-only log | — | no analog |

---

## Pattern Assignments

### `app/eval/retrieval.py` (CLI script, batch)

**Analog:** `app/eval/author.py`

**Imports pattern** (author.py lines 35–51):
```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.db import get_conn
from app.embeddings.factory import get_embedder
from app.eval.schema import GoldenTuple, load_golden_set
from app.retrieval.base import ChunkResult, retrieve
```

**build_parser() pattern** (author.py lines 320–364):
```python
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.eval.retrieval",
        description="...",
    )
    p.add_argument("--held-out", action="store_true", default=True,
                   help="Score only the 5 held-out tuples (default)")
    p.add_argument("--all", dest="held_out", action="store_false",
                   help="Score all 22 tuples")
    p.add_argument("--k", type=int, default=8)
    p.add_argument("--golden-set", type=Path, default=Path("eval/golden_set.jsonl"))
    p.add_argument("--runs-log", type=Path, default=Path("eval/runs.jsonl"))
    return p
```

**main() entry point pattern** (author.py lines 367–479 + ingest/pipeline.py lines 78–188):
```python
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    embedder = get_embedder()   # raises if EMBEDDING_MODEL unimplemented — fail fast
    conn = get_conn()
    try:
        # ... main body
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    sys.exit(main())
```

**Injected-dep pattern for unit-testability** (base.py lines 116–149):
```python
def score_tuple(
    t: GoldenTuple,
    k: int = 8,
    conn=None,
    embedder=None,
) -> dict:
    """conn=None → get_conn(); embedder=None → get_embedder(). Same as retrieve()."""
    results: list[ChunkResult] = retrieve(t.query, k=k, conn=conn, embedder=embedder)
    retrieved_ids = [r.chunk_id for r in results]
    ...
```
The pattern is: default `None` parameters fall back to live singletons; tests inject fakes. Copy from `app/retrieval/base.py` lines 116–149 — the `conn or get_conn()` / `embedder or get_embedder()` split.

**runs.jsonl append pattern** (no existing analog — use RESEARCH.md code):
```python
import json
from datetime import datetime, timezone
from pathlib import Path

def load_last_run(path: Path) -> dict | None:
    if not path.exists():
        return None
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(lines[-1]) if lines else None

def append_run(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
```
File-open convention mirrors `app/eval/schema.py` lines 109–111 (`ensure_ascii=False`, `encoding="utf-8"`, `path.parent.mkdir(parents=True, exist_ok=True)`).

**No f-string SQL guard** — retrieval.py calls `retrieve()` exclusively, never writes raw SQL. The static test (see `tests/test_eval_retrieval.py` below) scans the module just as `test_retrieval.py` scans `app/retrieval/base.py` lines 374–386.

---

### `app/eval/ragas.py` (CLI script, batch + Anthropic API)

**Analogs:** `app/eval/author.py` (CLI skeleton) + `app/generation/generator.py` (Anthropic client usage)

**Imports pattern:**
```python
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from anthropic import Anthropic, AsyncAnthropic   # sync for claim calls; async for stream_response
from app.db import get_conn
from app.embeddings.factory import get_embedder
from app.eval.schema import GoldenTuple, load_golden_set
from app.generation.generator import stream_response
from app.generation.prompt import build_messages, build_system_blocks
from app.retrieval.base import ChunkResult, retrieve
```
Note: Never `import openai` directly — only `get_embedder()`. Static test in `tests/test_eval_ragas.py` enforces this (same pattern as `tests/test_generation.py` lines 343–357).

**asyncio.run() wrapper for stream_response()** (generator.py lines 44–119, test_generation.py lines 214–226):
```python
def generate_answer_sync(client: AsyncAnthropic, query: str,
                          sources_with_ids: list) -> str:
    """Synchronously collect full text from stream_response()."""
    async def _run() -> str:
        parts: list[str] = []
        async for sse in stream_response(
            client=client,
            system_blocks=build_system_blocks(),
            messages=build_messages([], query, sources_with_ids),
            sources_with_ids=sources_with_ids,
            session_id="eval-faithfulness",
        ):
            if sse.event is None:
                payload = json.loads(sse.data)
                if "text" in payload:
                    parts.append(payload["text"])
        return "".join(parts)
    return asyncio.run(_run())
```
The `sse.event is None` guard and `json.loads(sse.data)` pattern come from generator.py's token event shape (line 97: `yield ServerSentEvent(data=json.dumps({"text": text}))`).

**Two-step Anthropic claim decomposer** (RESEARCH.md — no existing codebase analog):
```python
# Step 1: sync client — no streaming needed for claim calls
sync_client = Anthropic()

response = sync_client.messages.create(
    model=get_settings().anthropic_model,
    max_tokens=512,
    system=CLAIM_EXTRACT_SYSTEM,
    messages=[{"role": "user", "content": CLAIM_EXTRACT_USER.format(answer=answer_text)}],
)
claims = parse_claims(response.content[0].text)

# Step 2: per claim
for claim in claims:
    r = sync_client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=64,
        system=CLAIM_SUPPORT_SYSTEM,
        messages=[{"role": "user", "content": CLAIM_SUPPORT_USER.format(
            claim=claim, chunk_texts="\n---\n".join(chunk.text for chunk in chunks))}],
    )
    supported = parse_support(r.content[0].text)
```
Use `sync_client.messages.create()` (non-streaming) for both steps. The `AsyncAnthropic` client is only used inside the `asyncio.run()` wrapper for `stream_response()`.

**CLI main() structure** — identical to `app/eval/author.py` lines 367–479 and `app/ingest/pipeline.py` lines 78–188: `build_parser()` → `main(argv=None)` → `if __name__ == "__main__": sys.exit(main())`.

---

### `tests/test_eval_retrieval.py` (test, batch unit + integration)

**Analog:** `tests/test_retrieval.py`

**File header and imports pattern** (test_retrieval.py lines 1–21):
```python
"""Retrieval eval scorer tests — Phase 5 Plan 1.

N named tests total: N offline unit + 1 live-DB integration (skipped when Postgres unavailable).

Covers:
  - recall_at_k() and reciprocal_rank() metric functions (EVAL-02)
  - append_run() / load_last_run() file helpers (EVAL-02)
  - format_diff() output format (EVAL-02)
  - CLI --help (EVAL-02)
  - Static guard: no f-string SQL in app/eval/retrieval.py (CLAUDE.md)
  - Live integration: scorer run against real DB (EVAL-02)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
```

**db_conn fixture** (test_retrieval.py lines 44–62) — copy verbatim:
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

**_FakeEmbedder pattern** (test_retrieval.py lines 94–112) — copy for integration tests:
```python
class _FakeEmbedder:
    model = "text-embedding-3-small"
    dim = 1536
    provider = "openai"

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * 1536

    def embed_documents(self, texts):
        from app.embeddings.base import EmbeddingResult
        return EmbeddingResult(
            vectors=[[0.0] * 1536] * len(list(texts)),
            model=self.model, dim=self.dim, provider=self.provider,
        )
```

**Static f-string SQL guard pattern** (test_retrieval.py lines 374–386):
```python
def test_no_fstring_sql_in_retrieval_scorer():
    scorer_path = Path(__file__).resolve().parent.parent / "app" / "eval" / "retrieval.py"
    assert scorer_path.exists(), "app/eval/retrieval.py not found"
    contents = scorer_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"""f["'][^"']*\{[^"']*(SELECT|INSERT|UPDATE|DELETE|TRUNCATE)[^"']*["']""",
        re.IGNORECASE,
    )
    offenders = [line for line in contents.splitlines() if pattern.search(line)]
    assert offenders == [], f"f-string SQL found in retrieval.py: {offenders}"
```

**Live integration test gating** (test_retrieval.py lines 426–448) — use the `db_conn` fixture skip mechanism. Apply same pattern for scorer integration test.

**Import-inside-function pattern** — all test_retrieval.py tests import from app inside the function body (`from app.eval.retrieval import recall_at_k  # type: ignore[import-not-found]`). This matches the Phase 3 convention from test_generation.py so test collection succeeds even before the file exists.

---

### `tests/test_eval_refusal.py` (test, request-response via async generator)

**Analog:** `tests/test_generation.py`

**_FakeAnthropicStream + _FakeAnthropicClient pattern** (test_generation.py lines 61–98) — copy verbatim, no changes:
```python
class _FakeAnthropicStream:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def __aenter__(self) -> "_FakeAnthropicStream":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    @property
    def text_stream(self):
        async def _gen():
            for t in self._tokens:
                yield t
        return _gen()


class _FakeAnthropicClient:
    def __init__(self, tokens: list[str] | None = None) -> None:
        self._tokens = tokens if tokens is not None else ["hello"]
        self.messages = _FakeMessages(self._tokens)


class _FakeMessages:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    def stream(self, **kwargs: object) -> _FakeAnthropicStream:
        return _FakeAnthropicStream(self._tokens)
```

**asyncio.run() in sync test pattern** (test_generation.py lines 214–226) — the collect-response coroutine and `asyncio.run()` call:
```python
async def _collect(client, sources_with_ids):
    parts: list[str] = []
    async for sse in stream_response(
        client=client,
        system_blocks=build_system_blocks(),
        messages=build_messages([], "Get EVH gain tone", sources_with_ids),
        sources_with_ids=sources_with_ids,
        session_id="test-refusal",
    ):
        if sse.event is None:
            p = json.loads(sse.data)
            if "text" in p:
                parts.append(p["text"])
    return "".join(parts)

def test_empty_context_produces_refusal():
    fake = _FakeAnthropicClient(tokens=["I don't have material on EVH"])
    text = asyncio.run(_collect(fake, sources_with_ids=[]))
    assert any(phrase in text for phrase in ("I don't have material", "the closest I have"))
```
Critical: test `stream_response()` directly, NEVER via HTTP endpoint. The `test_main.py` HTTP path uses `raise_server_exceptions=False` which silently swallows `TypeError` from parameter name mismatches (sources= vs sources_with_ids=).

**_reset_sessions autouse fixture** (test_generation.py lines 105–123) — copy verbatim for refusal tests:
```python
@pytest.fixture(autouse=True)
def _reset_sessions():
    try:
        import app.session as s
        s._sessions.clear()
    except (ImportError, AttributeError):
        pass
    yield
    try:
        import app.session as s
        s._sessions.clear()
    except (ImportError, AttributeError):
        pass
```

**Live integration test gating** — use `ANTHROPIC_API_KEY` env var (not `db_conn`). Pattern from RESEARCH.md:
```python
@pytest.fixture
def anthropic_key():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set — skipping live refusal test")
    return key
```

**ChunkResult construction for adversarial test** — construct inline using the frozen dataclass constructor. Copy field names from `app/retrieval/base.py` lines 38–62:
```python
from app.retrieval.base import ChunkResult

_LO_FI_CHUNKS = [
    ChunkResult(
        chunk_id="11547f9a-2b6b-4074-a301-80113ee72bea",
        document_id="doc-lofi-1",
        source_type="forum",
        source_name="lo_fi_tone.txt",
        chunk_index=0,
        text="For lo-fi bedroom guitar tone, use a cheap amp mic'd badly with tape hiss.",
        distance=0.6,
    ),
]
```
Wrap `ChunkResult` in `(chunk, sn)` tuple pairs (`sources_with_ids`) to match `stream_response()`'s `list[tuple[ChunkResult, int]]` signature (generator.py line 49).

---

### `tests/test_eval_ragas.py` (test, batch unit + integration)

**Analogs:** `tests/test_generation.py` (fake Anthropic client) + `tests/test_retrieval.py` (db_conn + static guard)

**File header pattern** — same import structure as test_generation.py lines 1–28 but without `pytest-asyncio`. All async helpers called via `asyncio.run()` in sync test functions.

**_FakeCreateMessages pattern** — RAGAS uses `sync_client.messages.create()`, not `.stream()`. Build a separate fake:
```python
class _FakeCreateResponse:
    """Minimal fake for Anthropic sync .messages.create() response."""
    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]

class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text

class _FakeCreateMessages:
    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)

    def create(self, **kwargs: object) -> _FakeCreateResponse:
        return _FakeCreateResponse(next(self._responses))

class _FakeSyncClient:
    def __init__(self, responses: list[str]) -> None:
        self.messages = _FakeCreateMessages(responses)
```
This is distinct from `_FakeAnthropicClient` in test_generation.py (which only has `.messages.stream()`). RESEARCH.md Pitfall 6 calls this out explicitly.

**Static no-openai-import guard** (test_generation.py lines 343–357) — same pattern, scans `app/eval/` instead of `app/generation/`:
```python
def test_no_direct_openai_import_in_eval():
    eval_dir = Path(__file__).resolve().parent.parent / "app" / "eval"
    assert eval_dir.exists(), f"app/eval/ not found at {eval_dir}"
    pattern = re.compile(r"^(from openai\b|import openai\b)", re.MULTILINE)
    violators = [
        str(f)
        for f in eval_dir.rglob("*.py")
        if pattern.search(f.read_text(encoding="utf-8"))
    ]
    assert violators == [], f"Direct openai import in app/eval/: {violators}"
```

**db_conn fixture** — copy verbatim from test_retrieval.py lines 44–62 (same as test_eval_retrieval.py).

**Pure-function unit tests** — `parse_claims()`, `parse_support()`, and `faithfulness_score()` are pure functions testable without any client or DB. Test them first, completely offline, before the integration tier.

---

### `eval/runs.jsonl` (data file, append-only log)

No code analog. This is a new JSONL log file created on first CLI run. Schema per D-10:
```json
{"timestamp": "2026-05-28T12:00:00+00:00", "k": 8, "scope": "held_out",
 "recall_at_1": 0.80, "recall_at_5": 0.80, "recall_at_8": 1.00, "mrr": 0.90,
 "embedding_model": "text-embedding-3-small"}
```
Faithfulness runs go to `eval/faithfulness_runs.jsonl` (separate file, per RESEARCH.md recommendation A2).

---

## Shared Patterns

### No Direct openai Import (CLAUDE.md hard constraint)
**Source:** `tests/test_generation.py` lines 343–357; `tests/test_retrieval.py` lines 393–405
**Apply to:** All files in `app/eval/`
```python
pattern = re.compile(r"^(from openai\b|import openai\b)", re.MULTILINE)
```
Add one static test per test file that scans the corresponding `app/eval/` module(s).

### Injected Dependencies (conn=None, embedder=None)
**Source:** `app/retrieval/base.py` lines 116–177
**Apply to:** `app/eval/retrieval.py` scorer functions, `app/eval/ragas.py` answer-generation helper
```python
_conn = conn or get_conn()
_should_close = conn is None
_embedder = embedder or get_embedder()
```
Always use `try/finally: _conn.close()` if `_should_close`.

### asyncio.run() in Sync Tests (not pytest-asyncio)
**Source:** `tests/test_generation.py` Tests 5–8 (lines 206–335)
**Apply to:** All test files that call `stream_response()` helpers
No pytest-asyncio is installed. Write sync test functions. Define async inner helpers (e.g., `async def _collect(...)`) and call them via `asyncio.run()`. Never call `asyncio.run()` from inside an async test or fixture.

### Import-Inside-Test-Function
**Source:** `tests/test_generation.py` lines 132, 155, 188, 209, etc.
**Apply to:** All three new test files
```python
def test_recall_at_k_hit():
    from app.eval.retrieval import recall_at_k  # type: ignore[import-not-found]
    assert recall_at_k(["id-1"], ["id-1", "id-2"], 1) == 1.0
```
This pattern lets pytest collect tests before the target module exists, preserving RED→GREEN discipline.

### db_conn Fixture (live-gated)
**Source:** `tests/test_retrieval.py` lines 44–62 (also verbatim in `tests/test_main.py` lines 17–34)
**Apply to:** `tests/test_eval_retrieval.py` and `tests/test_eval_ragas.py`
Copy verbatim — no modification needed.

### _reset_sessions autouse Fixture
**Source:** `tests/test_generation.py` lines 105–123 (also in `tests/test_main.py` lines 42–57)
**Apply to:** `tests/test_eval_refusal.py` (calls stream_response() which touches session state)
Copy verbatim — prevents cross-test session bleed.

### f-string SQL Static Guard
**Source:** `tests/test_retrieval.py` lines 374–386
**Apply to:** `tests/test_eval_retrieval.py` (scans `app/eval/retrieval.py`)
The regex pattern is: `r"""f["'][^"']*\{[^"']*(SELECT|INSERT|UPDATE|DELETE|TRUNCATE)[^"']*["']"""` with `re.IGNORECASE`.

### `__main__` Entry Point
**Source:** `app/ingest/pipeline.py` line 187; `app/eval/author.py` line 482–483
**Apply to:** `app/eval/retrieval.py` and `app/eval/ragas.py`
```python
if __name__ == "__main__":  # pragma: no cover — invoked via python -m
    sys.exit(main())
```

### SYSTEM_PROMPT_TEXT Refusal Phrases
**Source:** `app/generation/prompt.py` lines 43–44
**Apply to:** `tests/test_eval_refusal.py` assertion helpers
The exact phrases from the system prompt rule 2 are:
- `"I don't have material"`
- `"the closest I have"`
```python
REFUSAL_PHRASES = ("I don't have material", "the closest I have")
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `eval/runs.jsonl` | data file | append-only | No existing append-only log file in project; created on first run |

The `append_run()` / `load_last_run()` helpers in `app/eval/retrieval.py` use the same `json.dumps(..., ensure_ascii=False)` + `path.open("a", encoding="utf-8")` pattern seen in `app/eval/schema.py` lines 109–111, adapted for append mode.

---

## Critical Pitfalls (Planner Must Surface in Plan Actions)

1. **sources= vs sources_with_ids= mismatch** — `tests/test_main.py` uses `sources=` but `stream_response()` requires `sources_with_ids=`. Phase 5 tests MUST test `stream_response()` directly, never via HTTP. Source: RESEARCH.md Pitfall 5.

2. **`asyncio.run()` inside an already-running loop** — no pytest-asyncio in venv. All async helpers must be called via `asyncio.run()` inside sync test functions. Source: RESEARCH.md Pitfall 3.

3. **Two distinct fake clients needed** — `_FakeAnthropicClient` (has `.messages.stream()`) for refusal tests; `_FakeSyncClient` (has `.messages.create()`) for RAGAS unit tests. Do not conflate. Source: RESEARCH.md Pitfall 6.

4. **Any-hit recall semantics** — `recall_at_k()` must use `any(eid in top_k_set for eid in expected_ids)`, not all-hit semantics. Source: RESEARCH.md Pitfall 1.

5. **Vector() wrapper** — always call `retrieve()` from eval scripts, never write raw cosine SQL. Source: RESEARCH.md Pitfall 2.

---

## Metadata

**Analog search scope:** `app/eval/`, `app/retrieval/`, `app/generation/`, `app/ingest/`, `tests/`
**Files scanned:** 7 (author.py, pipeline.py, base.py, generator.py, prompt.py, schema.py, test_generation.py, test_retrieval.py, test_main.py)
**Pattern extraction date:** 2026-05-28
