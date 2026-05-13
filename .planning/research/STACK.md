# Stack Research: Guitar Tone Advisor

**Domain:** Personal Python RAG web app (guitar tone recommendations)
**Researched:** 2026-05-13
**Overall confidence:** HIGH for versions and library identity (verified directly against PyPI on the research date); MEDIUM for behavioural claims about each library (based on training data plus stable, well-known library reputations); MEDIUM-LOW for any "is X still maintained?" claims about smaller libraries — flagged inline.

> Tool note: WebSearch / WebFetch were denied in this environment. All version numbers below were verified by querying `https://pypi.org/pypi/<package>/json` directly via `curl` on 2026-05-13. Behavioural recommendations rely on stable, well-documented library behaviour from training data. Where a recommendation could plausibly have shifted recently, I have flagged it.

---

## Recommended Stack Summary

| Concern | Recommendation | Version (PyPI, 2026-05-13) | Install |
|---|---|---|---|
| Web framework | **FastAPI** | 0.136.1 | `pip install fastapi` |
| ASGI server | **uvicorn** (standard extras) | 0.46.0 | `pip install 'uvicorn[standard]'` |
| Settings / env | **pydantic-settings** + **python-dotenv** | 2.14.1 / 1.2.2 | `pip install pydantic-settings python-dotenv` |
| Postgres driver | **psycopg** (v3, sync + async) | 3.3.4 | `pip install 'psycopg[binary]'` |
| pgvector adapter | **pgvector** (Python client) | 0.4.2 | `pip install pgvector` |
| LLM SDK | **anthropic** | 0.102.0 | `pip install anthropic` |
| Default embeddings | **openai** | 2.36.0 | `pip install openai` |
| Optional embeddings | **voyageai** | 0.3.7 | `pip install voyageai` |
| Local fallback embeddings | **sentence-transformers** | 5.5.0 | `pip install sentence-transformers` |
| PDF text (born-digital) | **pypdf** | 6.11.0 | `pip install pypdf` |
| PDF rich / tables / images | **PyMuPDF** + **pymupdf4llm** | 1.27.2.3 / 1.27.2.3 | `pip install pymupdf pymupdf4llm` (AGPL — see note) |
| HTML article extraction | **trafilatura** | 2.0.0 | `pip install trafilatura` |
| HTTP client | **httpx** | 0.28.1 | `pip install httpx` |
| YouTube transcripts | **youtube-transcript-api** | 1.2.4 | `pip install youtube-transcript-api` |
| YouTube fallback | **yt-dlp** | 2026.3.17 | `pip install yt-dlp` |
| Retry / backoff | **tenacity** | 9.1.4 | `pip install tenacity` |
| Token counting | **tiktoken** | 0.12.0 | `pip install tiktoken` |
| SSE streaming helper | **sse-starlette** | 3.4.4 | `pip install sse-starlette` |
| Chunking | **stdlib + small custom code** (optionally semchunk 4.0.0) | — | — |

> The complete `requirements.txt` is at the end of this document.

**`psycopg2-binary` vs `psycopg[binary]`:** Use **psycopg v3** (`psycopg[binary]==3.3.4`). The project context specifies `psycopg2`, but `psycopg` v3 is the modern successor by the same maintainer team, has first-class `pgvector` adapter support, supports both sync and async on a single connection, and integrates cleanly with FastAPI. If you have a hard reason to stay on psycopg2-binary (2.9.12), the `pgvector` package supports that path too — but new code should default to psycopg3. **Decision recorded.**

---

## PDF Parsing

**15 PDFs of guitar/amp/pedal manuals.** These typically contain: front-cover marketing art, block-diagrams (raster), I/O panel illustrations, parameter tables (knob name → range → description), schematic-style figures, occasional MIDI CC charts. Text is almost always born-digital (no OCR needed) except for occasional scanned vintage manuals.

### Recommendation

**Primary: `pypdf==6.11.0`** for the boring 80% (text-only manuals).
**Escalation: `PyMuPDF==1.27.2.3` + `pymupdf4llm==1.27.2.3`** for manuals where tables / multi-column layout matter.

Use a two-tier strategy: try `pypdf` first; if a manual fails a sanity check (very low character density, or known table-heavy manual), reprocess with `pymupdf4llm.to_markdown()` which preserves table structure and reading order as Markdown — directly chunkable for RAG.

### Why

- **`pypdf` (6.11.0)** — Pure-Python, permissive **BSD-3** license, actively maintained (this is the modern fork; `PyPDF2` is the deprecated name). Fastest install, no system deps. Adequate for clean born-digital PDFs.
- **`PyMuPDF` (1.27.2.3)** — Best-in-class text extraction quality (preserves reading order, handles columns, extracts text from inside vector graphics). The `pymupdf4llm` companion library outputs **Markdown with tables**, which is the single most useful primitive for a RAG corpus. Confidence: HIGH on quality, HIGH on AGPL license (verified via PyPI metadata).
- **`pdfplumber` (0.11.9)** — Better than `pypdf` at *visually inspecting* tables; worse than `pymupdf4llm` at *outputting Markdown*. Skip unless you need to draw bounding boxes during debugging.
- **`pdfminer.six` (20260107)** — The low-level library `pdfplumber` is built on. No reason to use directly.

### License gotcha (must read)

**PyMuPDF is dual-licensed AGPL-3.0 / commercial.** AGPL is fine for a fully local personal app that is never distributed or exposed as a network service to third parties — which exactly matches this project's "fully local deployment, no hosting, single user" constraints. **Decision: AGPL is acceptable here.** If you ever publish the project as a hosted service for others, AGPL Section 13 would require you to release server-side source.

### Gotchas

- `pypdf.PdfReader(...).pages[i].extract_text()` can return `""` for image-only pages. Always check `len(text.strip()) > 0` before chunking.
- `pymupdf4llm.to_markdown(path)` returns one big Markdown string for the whole document — you'll want to split by `## ` headings before chunking.
- Scanned vintage manuals (rare here) will need OCR. **Do not** install `unstructured` or `marker-pdf` for this — they pull in PyTorch / OpenCV / detectron2 weights (multi-GB) and are absurd overkill for 15 files. If a scanned manual appears, run `ocrmypdf` once at the CLI to bake OCR into the PDF, then re-process with pypdf.
- `pdfplumber` and `pypdf` will both happily emit ligature glyphs (`ﬁ`, `ﬂ`); normalise with `unicodedata.normalize("NFKC", text)` before storing.

---

## Web Article Scraping

10 Premier Guitar article URLs. These are static editorial pages with a clear "main article body" surrounded by site chrome (nav, ads, "related stories", comments).

### Recommendation

**`trafilatura==2.0.0`** as primary, with **`httpx==0.28.1`** for the HTTP layer if you want explicit control of timeouts / retries.

```python
import trafilatura
downloaded = trafilatura.fetch_url(url)            # uses urllib internally
article   = trafilatura.extract(
    downloaded,
    include_comments=False,
    include_tables=True,
    favor_precision=True,
    output_format="markdown",
)
```

### Why

- **`trafilatura` (2.0.0)** — Purpose-built for editorial article extraction. It strips boilerplate (nav, ads, related links) far more reliably than hand-rolled BeautifulSoup selectors and does not require maintaining per-site rules. Outputs Markdown directly. Confidence: HIGH for static editorial pages; MEDIUM that Premier Guitar specifically renders cleanly server-side (it historically does — flag this for verification when actually fetching).
- **`newspaper3k` (0.2.8)** — **AVOID.** Last meaningful release was 2018; the package is effectively abandoned. Trafilatura is its direct successor in this niche and benchmarks better. Confidence: HIGH (version 0.2.8 with old release date is plainly visible on PyPI).
- **`BeautifulSoup4` + `requests`** — Reach for this only if a specific page resists trafilatura. Keep it as a debugging escape hatch.
- **`playwright` (1.59.0)** — Only if Premier Guitar gates content behind JS rendering (it doesn't, as of training cutoff). Massive dependency for 10 pages; **don't install unless required.**

### Gotchas

- `trafilatura.fetch_url` honours `robots.txt`. Premier Guitar's robots is permissive for editorial pages, but it's polite to add `time.sleep(1.0)` between fetches at 10-URL scale anyway.
- If any URL is a `/podcast/` or `/video/` page, the "article body" may be a short blurb — trafilatura will return very little text. Detect with `len(article) < 500` and either skip or fall back to BeautifulSoup with a manual selector.
- Cache HTML to disk (`raw_data/web_html/<slug>.html`) on first fetch so re-runs of the indexing pipeline don't hammer the site. This is also a paper trail for citations.

---

## YouTube Transcript Fetching

### Recommendation

**`youtube-transcript-api==1.2.4`** as primary.
**`yt-dlp==2026.3.17`** as fallback only when transcripts are unavailable or the API is blocked.

```python
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

api = YouTubeTranscriptApi()
try:
    transcript = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
    # transcript is iterable of FetchedTranscriptSnippet(text, start, duration)
except (TranscriptsDisabled, NoTranscriptFound):
    # fallback to yt-dlp --write-auto-subs
    ...
```

### Why

- **`youtube-transcript-api` (1.2.4)** — Pure Python, no headless browser, MIT licensed (verified on PyPI). Returns timestamped snippets that are perfect for time-anchored citations (e.g. "see 4:32"). Confidence: HIGH on identity; MEDIUM-LOW that YouTube has not changed transcript endpoints recently — this library has historically broken once or twice when YouTube changed internals, so pin the version and have the yt-dlp fallback ready.
- **`yt-dlp` (2026.3.17)** — Heavy-duty downloader; supports subtitle extraction via `--write-subs --write-auto-subs --skip-download --sub-format vtt`. More resilient when YouTube blocks the lightweight API, but requires parsing VTT and is far heavier. Confidence: HIGH on maintenance (yt-dlp releases monthly; version naming is calendar-based).

### Language selection pattern

Always pass an ordered fallback list: `languages=["en", "en-US", "en-GB"]`. If the video is not in English, the API can `.translate("en")` an auto-generated transcript — but translated auto-captions are noisy and should be marked in metadata so the retriever can downweight them later.

### Gotchas

- **No transcripts on music videos.** Many guitar gear demos on YouTube have music-only segments where auto-captions are gibberish or absent. Always handle `NoTranscriptFound` and skip rather than crash.
- **IP rate limiting from YouTube** is possible at corpus-build time. Implement exponential backoff via `tenacity` and cache fetched transcripts to `raw_data/transcripts/<video_id>.json`.
- **API breakage risk.** YouTube has changed internals several times in the past; pin `youtube-transcript-api==1.2.4` in `requirements.txt` and have a documented runbook to upgrade or swap to yt-dlp.
- Transcript timestamps are seconds-from-start. Store them as `float` in the chunk metadata so citation links like `https://youtu.be/{id}?t={int(start)}` are trivially constructable.

---

## Embedding Generation & Abstraction

**Default v1:** `text-embedding-3-small` via `openai==2.36.0` (1536 dims).
**Configurable swap:** Voyage AI (`voyage-3-large` or `voyage-3.5`, 1024–2048 dims) via `voyageai==0.3.7`, or local `sentence-transformers==5.5.0` (e.g. `BAAI/bge-small-en-v1.5`, 384 dims).

### The abstraction (concrete code)

The retrieval code must never import `openai` or `voyageai` directly. It calls an embedder protocol.

```python
# app/embeddings/base.py
from typing import Protocol, Sequence
from dataclasses import dataclass

@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]   # one vector per input
    model: str                   # e.g. "text-embedding-3-small"
    dim: int                     # e.g. 1536
    provider: str                # "openai" | "voyage" | "local"

class Embedder(Protocol):
    model: str
    dim: int
    provider: str
    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult: ...
    def embed_query(self, text: str) -> list[float]: ...
```

```python
# app/embeddings/openai_embedder.py
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from .base import Embedder, EmbeddingResult

_DIMS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072}

class OpenAIEmbedder:
    provider = "openai"
    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model
        self.dim = _DIMS[model]
        self._client = OpenAI()  # reads OPENAI_API_KEY

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(min=1, max=30))
    def embed_documents(self, texts):
        resp = self._client.embeddings.create(model=self.model, input=list(texts))
        return EmbeddingResult(
            vectors=[d.embedding for d in resp.data],
            model=self.model, dim=self.dim, provider=self.provider,
        )

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text]).vectors[0]
```

```python
# app/embeddings/voyage_embedder.py
import voyageai
from .base import EmbeddingResult

class VoyageEmbedder:
    provider = "voyage"
    def __init__(self, model: str = "voyage-3-large", dim: int = 1024):
        self.model, self.dim = model, dim
        self._client = voyageai.Client()  # reads VOYAGE_API_KEY

    def embed_documents(self, texts):
        # Voyage requires input_type for asymmetric quality
        r = self._client.embed(list(texts), model=self.model, input_type="document")
        return EmbeddingResult(vectors=r.embeddings, model=self.model,
                               dim=self.dim, provider=self.provider)

    def embed_query(self, text):
        r = self._client.embed([text], model=self.model, input_type="query")
        return r.embeddings[0]
```

```python
# app/embeddings/factory.py
import os
def get_embedder():
    name = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    if name.startswith("text-embedding-3"):
        from .openai_embedder import OpenAIEmbedder
        return OpenAIEmbedder(model=name)
    if name.startswith("voyage-"):
        from .voyage_embedder import VoyageEmbedder
        return VoyageEmbedder(model=name)
    if name.startswith("local:"):
        from .local_embedder import LocalEmbedder
        return LocalEmbedder(model=name.removeprefix("local:"))
    raise ValueError(f"Unknown EMBEDDING_MODEL: {name}")
```

### Critical implementation notes

1. **Voyage AI has asymmetric document vs. query embedding** (`input_type="document"` at index time, `input_type="query"` at retrieval time) — OpenAI does not. The Protocol's two-method split (`embed_documents` vs `embed_query`) is what enables this without leaking provider concerns. Keep both methods even for OpenAI.
2. **Store `provider`, `model`, and `dim` in the DB alongside every vector.** If you switch models, you must re-embed everything — there is no "mix vectors from two models" path that gives sane results. Add a `WHERE embedding_model = $1` filter to retrieval queries.
3. **Don't use OpenAI's `dimensions=` parameter to shrink `text-embedding-3-large`** unless you commit to it forever — it bakes a truncation into the indexed vectors that you can't easily reverse.
4. **Batch embed at index time.** OpenAI accepts up to 2048 inputs per call (and ~300K tokens). Voyage accepts up to 128 inputs per call (verify in their docs). Batch in groups of 64 to be safe across providers.
5. **Local fallback rationale:** `sentence-transformers==5.5.0` lets you run the whole pipeline offline (no API key) for development and tests. `BAAI/bge-small-en-v1.5` is 384-dim and runs on CPU at acceptable speed for 15 PDFs + 10 articles + a handful of transcripts. Confidence: MEDIUM — sentence-transformers v5.x is recent; behaviour may have shifted from the well-known v2.x API. Verify before relying.

### What NOT to do

- Don't use `langchain-openai` or any LangChain embedding wrapper. The project explicitly excludes LangChain.
- Don't store raw vectors in JSON files "just for now." Putting them straight into pgvector from day one is barely more work and avoids a migration later.

---

## pgvector Schema

For a corpus this size (15 PDFs + 10 articles + ~20 transcripts ≈ 5K–20K chunks; well under 100K), keep it simple: one table, **HNSW** index on the vector column.

### DDL

```sql
-- One-time extension setup
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- enables ILIKE/trigram for hybrid search later

-- Sources catalogue (1 row per ingested document)
CREATE TABLE sources (
    source_id      BIGSERIAL PRIMARY KEY,
    source_type    TEXT NOT NULL CHECK (source_type IN ('forum', 'pdf_manual', 'web_article', 'youtube')),
    source_name    TEXT NOT NULL,           -- e.g. "Strymon Iridium Manual v1.3"
    source_url     TEXT,                    -- canonical URL or file path
    fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_hash   TEXT NOT NULL,           -- sha256 of raw bytes, for idempotent re-ingest
    metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_type, source_name)
);

-- Chunks table (1 row per retrievable passage)
CREATE TABLE chunks (
    chunk_id        BIGSERIAL PRIMARY KEY,
    source_id       BIGINT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,         -- 0-based position within source
    chunk_text      TEXT NOT NULL,
    char_count      INTEGER NOT NULL,
    token_count     INTEGER,                  -- from tiktoken at ingest time
    page_num        INTEGER,                  -- PDF only; NULL otherwise
    timestamp_sec   DOUBLE PRECISION,         -- YouTube only; NULL otherwise
    section_path    TEXT,                     -- e.g. "3.2 Reverb > Decay" for PDFs, "h2 > h3" for HTML
    embedding_model TEXT NOT NULL,            -- e.g. "text-embedding-3-small"
    embedding       vector(1536) NOT NULL,    -- DIM MATCHES embedding_model
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, chunk_index, embedding_model)
);

-- HNSW index for cosine similarity (the right default for OpenAI / Voyage embeddings)
CREATE INDEX chunks_embedding_hnsw_cos
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Btree filters that retrieval will hit
CREATE INDEX chunks_source_id_idx       ON chunks (source_id);
CREATE INDEX chunks_embedding_model_idx ON chunks (embedding_model);

-- Optional: trigram index for hybrid (lexical + semantic) search later
CREATE INDEX chunks_text_trgm_idx ON chunks USING gin (chunk_text gin_trgm_ops);
```

### Index choice: HNSW > IVFFlat (with caveats)

| Criterion | HNSW | IVFFlat |
|---|---|---|
| Recall at default settings | Higher | Lower |
| Build time | Slower | Faster |
| Memory | Higher | Lower |
| **Works on empty table?** | **Yes** | **No (requires data to "train" the lists parameter)** |
| Insert performance | Steady | Faster |
| Right pick for <100K chunks | **Yes** | No |

For a corpus under 100K chunks on a single user's laptop, HNSW with `m=16, ef_construction=64` is the right default. Tune `ef_search` per query (`SET LOCAL hnsw.ef_search = 40;`) if recall feels low. Confidence: HIGH on the choice (pgvector docs have been consistent on this since 0.5.0); HIGH on the parameter defaults being safe.

> **IVFFlat trap:** If you do choose IVFFlat, you must build the index **after** loading data, with `lists = sqrt(N)` where N is row count. Building IVFFlat on an empty table will silently produce a useless index. HNSW does not have this footgun.

### Why a `vector(1536)` column and not `vector` (unsized)?

pgvector requires the dimension at column definition time. If you plan to support multiple embedding models in the same database (e.g. for A/B), you have two options:

- **Option A (recommended for v1):** Single `embedding vector(1536)` column. Switching models means migrating: add new column, backfill, swap, drop old.
- **Option B:** Separate tables per model: `chunks_openai_small`, `chunks_voyage_3`, etc. Cleaner but more bookkeeping.

For a single-user app, Option A is the right tradeoff. The `embedding_model` column is there so you can detect "wait, this row has the wrong dimension" defensively at retrieval time.

### Cosine vs L2 vs inner product

Use **cosine** (`vector_cosine_ops` in the index, `<=>` operator in queries). OpenAI and Voyage embeddings are already normalised; cosine is the correct distance for them and is the universal RAG default. Don't mix operators.

### Retrieval query template

```sql
SELECT
    c.chunk_id, c.chunk_text, c.page_num, c.timestamp_sec, c.section_path,
    s.source_type, s.source_name, s.source_url,
    1 - (c.embedding <=> $1::vector) AS cosine_similarity
FROM chunks c
JOIN sources s ON s.source_id = c.source_id
WHERE c.embedding_model = $2
ORDER BY c.embedding <=> $1::vector
LIMIT $3;
```

---

## FastAPI Project Layout

### Layout

```
guitar-tone-advisor/
├── pyproject.toml                 # or requirements.txt; pick one
├── .env                           # local secrets (gitignored)
├── .env.example                   # committed template
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app factory + middleware
│   ├── config.py                  # pydantic-settings Settings class
│   ├── db.py                      # psycopg connection pool + pgvector register
│   ├── deps.py                    # FastAPI Depends() providers
│   ├── api/
│   │   ├── __init__.py
│   │   ├── health.py              # GET /healthz
│   │   └── chat.py                # POST /chat (streaming)
│   ├── embeddings/
│   │   ├── base.py                # Embedder Protocol (see above)
│   │   ├── openai_embedder.py
│   │   ├── voyage_embedder.py
│   │   ├── local_embedder.py
│   │   └── factory.py
│   ├── retrieval/
│   │   ├── retriever.py           # vector search, returns ranked chunks
│   │   └── prompts.py             # system + retrieval-grounded prompt builders
│   ├── generation/
│   │   └── claude_client.py       # thin wrapper around anthropic SDK
│   ├── ingest/                    # CLI scripts, not imported by FastAPI
│   │   ├── pdf.py
│   │   ├── web.py
│   │   ├── youtube.py
│   │   ├── forum.py
│   │   ├── chunker.py
│   │   └── pipeline.py            # python -m app.ingest.pipeline
│   └── models.py                  # pydantic request/response models
├── scripts/
│   └── init_db.sql                # the DDL above
├── tests/
└── raw_data/                      # gitignored; PDFs, scraped HTML, transcripts
```

### Key principles

- **Ingest is a CLI, not an API.** PDFs and articles are loaded once via `python -m app.ingest.pipeline`. The FastAPI app is read-only over the vector store. This keeps the request path simple and fast.
- **One global connection pool** in `app/db.py`, created at startup, closed at shutdown. Use `psycopg_pool.ConnectionPool` (sync) or `AsyncConnectionPool` (async).
- **Register pgvector once per connection.** From the `pgvector` Python client docs:
  ```python
  from pgvector.psycopg import register_vector
  with pool.connection() as conn:
      register_vector(conn)
  ```
  In a pool, register on every new connection via the pool's `configure=` hook.
- **Pydantic models for everything that crosses the API boundary.** Request bodies, response bodies, even internal `RetrievedChunk` dataclasses — easier debugging, easier serialisation to the frontend.

### Streaming pattern (Claude responses)

The frontend wants tokens to appear as they're generated. Use Anthropic's streaming API + SSE (Server-Sent Events) — *not* raw chunked HTTP, because EventSource on the browser is trivial and SSE handles reconnection.

```python
# app/api/chat.py
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse
from app.models import ChatRequest
from app.deps import get_retriever, get_claude

router = APIRouter()

@router.post("/chat")
async def chat(req: ChatRequest, retriever=Depends(get_retriever), claude=Depends(get_claude)):
    # 1. RETRIEVE (synchronous, fast, ~50ms for HNSW @ 10K chunks)
    chunks = retriever.search(req.message, k=8)

    # 2. BUILD PROMPT with citations
    prompt = build_grounded_prompt(req.message, chunks)

    # 3. STREAM GENERATION
    async def event_gen():
        # First event: send the retrieved chunks so the UI can render citations early
        yield {"event": "sources", "data": json.dumps([c.to_citation() for c in chunks])}

        async with claude.messages.stream(
            model="claude-sonnet-4-5",  # or whatever current model id you choose
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield {"event": "token", "data": text}
            yield {"event": "done", "data": ""}

    return EventSourceResponse(event_gen())
```

Confidence on the Anthropic streaming API surface: MEDIUM. The shape (`messages.stream(...).text_stream`) is from training data; verify against `anthropic==0.102.0` docs before implementing. The SSE pattern around it is solid regardless.

### Retrieval → generation pipeline (the canonical RAG loop)

1. Embed the user message: `vec = embedder.embed_query(req.message)`
2. Vector search: `chunks = retriever.search(vec, k=8)` — return text + source metadata
3. Build prompt: a system prompt forbidding ungrounded claims, plus the retrieved chunks as a `<context>` block, plus the user question
4. Stream Claude's response back to the client
5. Frontend renders citations from the `sources` event before tokens even start arriving

Do not put retrieval inside Claude tool-calls for v1. Direct retrieval is simpler, faster, and easier to debug. Tool-calling-based retrieval is a v2 feature once you have telemetry.

---

## Next.js + FastAPI Integration

### Local dev setup

- FastAPI runs on `localhost:8000` (uvicorn).
- Next.js runs on `localhost:3000` (`pnpm dev` / `npm run dev`).

### Option A (recommended): Next.js rewrites — no CORS

In `next.config.js`:

```js
module.exports = {
  async rewrites() {
    return [
      { source: '/api/py/:path*', destination: 'http://localhost:8000/:path*' },
    ];
  },
};
```

The browser sees same-origin requests to `/api/py/chat`; Next.js proxies to FastAPI. **No CORS configuration needed.** This is the cleanest local setup and mirrors a production reverse-proxy topology.

### Option B: explicit CORS

Only if you can't use rewrites (e.g. you want to call FastAPI directly from the browser in dev). Add to `app/main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Streaming from Next.js to the browser

Two layers:

1. **FastAPI → Next.js route handler:** the route handler in `app/api/chat/route.ts` proxies the SSE stream from FastAPI through to the browser. With Option A's rewrite this is automatic — just have the client `fetch('/api/py/chat')` and parse SSE.
2. **Browser:** use the native `EventSource` API, or `fetch` with a `ReadableStream` reader if you POST a body. Since `EventSource` is GET-only and your `/chat` is POST, use `fetch` + `response.body.getReader()` and parse `event:` / `data:` lines manually. There are also small libraries (e.g. `@microsoft/fetch-event-source`) that do this; for a one-endpoint app, hand-rolling 30 lines is fine.

### Production note (out of scope but worth recording)

You stated "fully local deployment, no hosting." If that ever changes, the standard topology is: Next.js + FastAPI behind a single reverse proxy (Caddy or nginx), and the rewrite pattern Just Keeps Working.

---

## Chunking Strategy per Source Type

**Global defaults:** Aim for chunks of ~400–800 tokens (≈1600–3200 characters of English). Embed with `text-embedding-3-small` (8K input limit — plenty of headroom). Always include a 50–100 token overlap *only* for prose (PDFs, articles). Forum posts and transcript windows get no overlap (see below).

Count tokens with `tiktoken==0.12.0` using the `cl100k_base` encoder (matches OpenAI embedding models).

### Forum posts (short, already topical)

- Treat **one post = one chunk**, unless the post is over ~1200 tokens.
- Posts over 1200 tokens: split on paragraph boundaries (double-newline), pack adjacent paragraphs up to ~800 tokens each, no overlap.
- Strip quoted reply blocks (lines starting with `>` or wrapped in `[quote]...[/quote]`) before chunking — quoting the parent post pollutes embeddings.
- Metadata: `{"author": ..., "thread_title": ..., "post_url": ..., "post_id": ...}`

### PDF manuals (section-based, tables)

- Process via `pymupdf4llm.to_markdown(path)` → one big Markdown string.
- Split on Markdown headings (`## `, `### `) first. Each section becomes a candidate chunk.
- If a section is > 800 tokens, sub-split on `\n\n` paragraph boundaries with 80-token overlap.
- If a section is < 100 tokens (e.g. a stubby "Specifications" header with a one-line list), **merge it with the next section** rather than indexing a tiny standalone chunk.
- Tables in `pymupdf4llm` come out as pipe-delimited Markdown. **Keep the whole table in one chunk** even if it pushes the chunk over 800 tokens — splitting a table mid-row destroys its meaning.
- Metadata: `{"page_num": ..., "section_path": "3.2 Reverb > Decay", "manufacturer": "Strymon", "product": "Iridium"}`
- `page_num` for a multi-page section: use the page where the section heading first appears.

### Web articles (paragraph-based)

- Extract Markdown via `trafilatura.extract(..., output_format="markdown")`.
- Same heading-first / paragraph-pack approach as PDFs, but with smaller target chunks (~500 tokens) — editorial articles tend to have shorter "thoughts per paragraph" than manuals.
- 80-token overlap between adjacent chunks within the same article.
- Strip image captions / pull-quotes that trafilatura leaves behind as standalone short paragraphs.
- Metadata: `{"article_title": ..., "article_url": ..., "author": ..., "published_at": ..., "section_path": "h2 > h3"}`

### YouTube transcripts (time-window)

- **Use sliding time-windows, not sentence-based splits.** Auto-captions rarely have correct punctuation, so sentence detection fails.
- Window: 60-second windows with 10-second overlap. At typical speech rates this yields ~150–250 word chunks (200–350 tokens) — slightly smaller than prose chunks, which is appropriate because spoken content is lower information density.
- Concatenate snippet `.text` within the window; record `timestamp_sec = window_start_seconds` (this lets you build `?t=` deep-links into the video).
- Metadata: `{"video_id": ..., "video_title": ..., "channel": ..., "window_start_sec": ..., "window_end_sec": ..., "is_auto_generated": true/false}`
- **Mark `is_auto_generated`** in metadata. Auto-captions on gear demos are notoriously noisy (mishears "Klon" as "clone", "EQD" as "EQ-D", etc.). Retrieval can downweight or hide these in the prompt if quality is poor.

### What about "semantic chunking"?

`semchunk==4.0.0` and `chonkie==1.6.6` offer embedding-driven chunk-boundary detection. **Skip them for v1.** They add a second pass of embedding calls at index time and the quality gain over heading-based chunking is marginal for well-structured manuals. Revisit only if retrieval quality is poor and you've already tried better metadata / hybrid search.

---

## What NOT to Use

### Explicitly excluded by project context

- **LangChain / langchain-core / langchain-community** — Excluded. The point of this project is to learn RAG from scratch. LangChain's abstractions hide the very things you want to understand (the embedding call, the SQL query, the prompt).
- **LlamaIndex / llama-index-core** — Same reason.
- **`langchain-text-splitters` (1.1.2)** — Even the "just the text splitters" sub-package pulls LangChain abstractions. Use stdlib `re.split` + token counting instead. The chunking logic above is ~150 lines of Python total.

### Likely to be reached for, should not be

| Package | Version | Why skip |
|---|---|---|
| `newspaper3k` | 0.2.8 | Abandoned since 2018; trafilatura is its successor. |
| `pypdf2` | (deprecated alias for pypdf) | Old name; use `pypdf` directly. |
| `unstructured` (0.22.28) | 0.22.28 | Pulls in detectron2 / PyTorch / OCR models. Multi-GB install, designed for "I want one tool to ingest anything." For 15 known PDFs it's massive overkill. |
| `marker-pdf` | 1.10.2 | Excellent quality but requires GPU and ~5GB of model weights. Only worth it if PDFs are visually complex AND text-extraction quality is unacceptable. |
| `docling` | 2.93.0 | IBM's general-purpose ingestion framework. Similar overhead to `unstructured`. Skip. |
| `pdfminer.six` | 20260107 | Low-level; use pypdf or PyMuPDF instead. |
| `playwright` | 1.59.0 | Heavy headless-browser dependency. Only add if a specific scrape target requires JS rendering. |
| `psycopg2-binary` | 2.9.12 | The mature predecessor of psycopg3. Works fine, but new code should target psycopg3 unless an existing codebase forces it. |
| `selectolax` | 0.4.8 | Fast HTML parser, but you're not parsing enough HTML to need it; BeautifulSoup is more readable for 10 pages. |
| `chromadb` / `qdrant-client` / `weaviate-client` | — | A second vector store on top of pgvector buys you nothing for a single-user local app and adds an entire dependency to operate. |
| `sentence-transformers` for the **default** path | 5.5.0 | Use as a **fallback** only. As default it adds PyTorch (~1GB) and gives lower retrieval quality than `text-embedding-3-small` on English RAG benchmarks. |
| Any reranker (Cohere Rerank, bge-reranker) | — | Not for v1. Add only if retrieval quality measurably underperforms. |

### Anti-pattern: rolling your own SQL escaping

Use `psycopg`'s parameterised queries (`%s`) for everything. Never f-string a vector or chunk text into a SQL statement — pgvector's `vector` type is a literal that psycopg + the `pgvector` Python adapter know how to bind correctly. With `register_vector(conn)`, you pass a numpy array or list directly as a parameter.

---

## Full `requirements.txt` (verified versions, 2026-05-13)

```
# Web framework
fastapi==0.136.1
uvicorn[standard]==0.46.0
sse-starlette==3.4.4
pydantic-settings==2.14.1
python-dotenv==1.2.2

# Database
psycopg[binary]==3.3.4
pgvector==0.4.2

# LLM + embeddings
anthropic==0.102.0
openai==2.36.0
voyageai==0.3.7                 # optional, only if EMBEDDING_MODEL=voyage-*
# sentence-transformers==5.5.0  # optional, only if EMBEDDING_MODEL=local:*

# Ingestion: PDFs
pypdf==6.11.0
pymupdf==1.27.2.3               # AGPL — fine for personal local-only app
pymupdf4llm==1.27.2.3

# Ingestion: web
trafilatura==2.0.0
httpx==0.28.1
beautifulsoup4==4.14.3          # escape hatch

# Ingestion: YouTube
youtube-transcript-api==1.2.4
yt-dlp==2026.3.17               # fallback only

# Utilities
tenacity==9.1.4
tiktoken==0.12.0
```

### Python version

All listed packages support Python ≥ 3.10. Recommend **Python 3.12** (mature, fast, broad wheel coverage). Avoid 3.13+ for now only because some scientific wheels can lag — verify on install.

### Confidence summary

| Recommendation | Confidence | Basis |
|---|---|---|
| All version numbers above | HIGH | Verified live against PyPI 2026-05-13 |
| PyMuPDF AGPL license | HIGH | Verified via PyPI license metadata |
| psycopg3 over psycopg2-binary | HIGH | Documented pgvector support; stable API since 3.1 |
| HNSW over IVFFlat at <100K chunks | HIGH | Long-standing pgvector guidance |
| trafilatura over newspaper3k | HIGH | newspaper3k abandonment is plainly visible from its 2018-era version |
| youtube-transcript-api as primary | MEDIUM | Library has had outages historically; pin version + keep yt-dlp fallback |
| Embedding abstraction pattern | HIGH | Conceptually straightforward; survives provider swaps |
| FastAPI streaming via SSE | HIGH | Standard pattern; sse-starlette is widely used |
| Anthropic SDK streaming surface (`messages.stream(...).text_stream`) | MEDIUM | From training data; confirm against `anthropic==0.102.0` docs before coding |
| sentence-transformers v5.x API as local fallback | MEDIUM-LOW | v5.x is recent; verify import/API surface before relying |
| Chunk size targets (400–800 tokens) | MEDIUM | Standard RAG practice; tune empirically once retrieval quality is measurable |

---

*Researched: 2026-05-13*
