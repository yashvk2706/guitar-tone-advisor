# Architecture Research: Guitar Tone Advisor

**Domain:** Personal RAG application over a small, hand-curated multi-format corpus (~48 source documents, expected <50K chunks).
**Researched:** 2026-05-13
**Overall confidence:** HIGH for structural decisions, MEDIUM for chunking parameter tuning (corpus-specific calibration needed in Phase 1).

> **Source-availability note:** Web search tooling was unavailable for this research run. Recommendations below draw on well-established RAG architecture patterns and the specific constraints in `PROJECT.md`. Where a parameter is corpus-sensitive (chunk size, top-K, overlap), the doc flags it as needing Phase 1 calibration rather than asserting a number as fact.

---

## System Overview

A **strict offline/online split**. Ingestion is a batch CLI process; the API is a thin retrieval+generation server. The two halves communicate **only through the Postgres/pgvector store** — no in-memory state, no shared queues, no Python imports across the boundary.

```
                                         RAW CORPUS (filesystem + URLs)
                                                    │
                                    ┌───────────────┴───────────────┐
                                    │   INGESTION (CLI, offline)    │
                                    │                               │
                                    │  loaders → normalizers →      │
                                    │  chunkers → embedder →        │
                                    │  upsert(documents, chunks)    │
                                    └───────────────┬───────────────┘
                                                    │
                                                    ▼
                                    ┌───────────────────────────────┐
                                    │   PostgreSQL + pgvector       │
                                    │                               │
                                    │  documents (source metadata)  │
                                    │  chunks    (text + embedding) │
                                    │  ingest_runs (audit)          │
                                    └───────────────┬───────────────┘
                                                    │
                                                    ▼
                                    ┌───────────────────────────────┐
                                    │   FastAPI (online)            │
                                    │                               │
                                    │  /chat:   embed → retrieve →  │
                                    │           rerank? → prompt →  │
                                    │           anthropic stream    │
                                    │  /sources/{chunk_id}          │
                                    │  /health, /ingest/status      │
                                    │                               │
                                    │  session memory: in-process   │
                                    │  dict keyed by session_id     │
                                    └───────────────┬───────────────┘
                                                    │
                                                    ▼
                                    ┌───────────────────────────────┐
                                    │   Next.js chat UI             │
                                    │   streams tokens + citations  │
                                    └───────────────────────────────┘
```

**Data flow direction is strictly one-way:** raw → ingestion → store → retrieval → generation → UI. The UI never writes to the store; ingestion never reads from session memory. This boundary is the most important architectural decision in the system because it makes every other component independently testable.

---

## Ingestion Pipeline

### Verdict: standalone CLI, not part of the API

Ingestion belongs in a `scripts/ingest.py` (or `python -m ingest`) entry point, **not** behind an HTTP endpoint. Reasons:

1. **Different runtime profile.** Ingestion is bursty, multi-minute, network-heavy (PDF parsing, embedding API calls, YouTube transcript fetching). The API should stay responsive.
2. **Different failure mode.** A failed embedding run should not crash the chat server; resuming a partial ingest is easier from a CLI with progress logging.
3. **Different access pattern.** Ingestion is run by you, on the same machine, with full filesystem access. No need for HTTP plumbing.
4. **Cleaner testing surface.** The ingestion pipeline can be unit-tested as pure functions (`load → normalize → chunk → embed → write`) without spinning up a server.

A thin `/ingest/status` endpoint on the API is useful for the UI to display "corpus contains N chunks across M sources" — but the endpoint reads from `ingest_runs` and `chunks`; it does not trigger ingestion.

### Component boundaries

```
┌─────────────┐    ┌──────────────┐    ┌──────────┐    ┌──────────┐    ┌─────────┐
│   Loader    │───▶│  Normalizer  │───▶│ Chunker  │───▶│ Embedder │───▶│ Writer  │
│ per source  │    │  → plain     │    │ strategy │    │  batch   │    │  upsert │
│   type      │    │    text +    │    │  per     │    │  to API  │    │  txn    │
│             │    │    metadata  │    │  source  │    │          │    │         │
└─────────────┘    └──────────────┘    └──────────┘    └──────────┘    └─────────┘
       │
   in:  path/url
   out: RawDocument(source_type, source_id, raw_bytes_or_text, fetch_metadata)
```

Each stage has a **typed dataclass boundary** so stages can be swapped (e.g., replace PyPDF2 with pdfplumber for one source) without touching neighbors.

### Re-ingestion: incremental by default, full-rebuild as escape hatch

**Content-hash-based dedup is the right pattern at this scale.** For each chunk, compute `sha256(normalized_text + source_id + chunk_index)` and store as the chunk's natural key. Re-running ingestion is then:

```
for each source:
    for each chunk:
        if chunk_hash already in DB with same embedding_model:
            skip
        else:
            embed + upsert
```

This handles:
- **Idempotent re-runs** (re-run the script after a crash, only missing chunks are re-embedded).
- **Source updates** (edit a forum post .txt, only changed chunks get new embeddings — others keep their stable IDs, so existing citations in chat history remain valid).
- **Embedding model swaps** (changing `EMBEDDING_MODEL` forces a full re-embed because hash includes the model dimension via a separate `embedding_model` column).

A `--full-rebuild` flag truncates `chunks` first for cases where the chunking strategy itself changed.

### Ingestion state

Two small tables alongside `chunks`:

```sql
documents (
  id              UUID PRIMARY KEY,
  source_type     TEXT NOT NULL,    -- 'forum' | 'manual' | 'article' | 'youtube'
  source_id       TEXT NOT NULL,    -- filename, URL, or YouTube video ID
  title           TEXT,
  fetched_at      TIMESTAMP,
  content_hash    TEXT,             -- sha256 of full normalized text
  metadata_json   JSONB,            -- artist, gear model, URL, duration, etc.
  UNIQUE (source_type, source_id)
);

ingest_runs (
  id              UUID PRIMARY KEY,
  started_at      TIMESTAMP,
  finished_at     TIMESTAMP,
  embedding_model TEXT,
  n_documents     INT,
  n_chunks        INT,
  status          TEXT,             -- 'running' | 'completed' | 'failed'
  error           TEXT
);
```

`ingest_runs` is the audit log that powers `/ingest/status`. `documents` is what lets you re-link a chunk back to its source for citation display.

### Deduplication across source types

There are three layers, in order of priority:

1. **Within a source (chunk dedup):** content-hash on chunk text. Catches re-runs.
2. **Across YouTube transcript chunks vs Premier Guitar quotes:** unlikely but possible (e.g., a YouTuber reading from an article). Apply a fuzzy near-duplicate filter (`difflib.SequenceMatcher` ratio > 0.9 between chunks with cosine similarity > 0.95 in embedding space) at *retrieval* time, not ingestion time — keep both chunks in the store but de-dup the top-K before passing to the LLM. Cheaper than O(N²) dedup at ingestion.
3. **Across manuals (Boss BD-2 manual quoting Boss DS-1 manual, etc.):** ignore. The corpus is too small for this to matter and each manual's context (filename, model) makes near-identical text retrieval-relevant in different ways.

---

## Chunking Architecture

### Per-source-type strategies

Chunking should be **dispatched on `source_type`**. A `Chunker` Protocol with four implementations:

#### Forum posts (`forum/*.txt`)
- **Strategy:** post-aware splitting if posts are delimited (e.g., `---` or `Post by:`); otherwise paragraph-grouping with a token budget.
- **Target chunk size:** 300–500 tokens. Forum posts are topic-dense and conversational — too-large chunks dilute the signal.
- **Overlap:** 50 tokens (sentence-aligned). Forum reasoning often spans paragraphs ("I tried X, then I tried Y, but Z worked because...").
- **Metadata:** `{topic: "bb_king_tone", post_index: 3, author: "?" if extractable}`.

#### PDF manuals (`manuals/*.pdf`)
- **Strategy:** section-aware. Use a PDF parser that preserves headings (pdfplumber or PyMuPDF). Build chunks from `(heading_path, paragraph_block)` where `heading_path` is e.g. `["Controls", "Tone Section"]`. Fall back to page-based chunking if heading detection fails for a given manual.
- **Tables:** linearize tables to text rows (`"Gain: 0–10 | Bass: 0–10 | Mid: 0–10"`) and treat each row as a chunk-eligible unit, prefixed by the table caption. Do not try to embed images of tables.
- **Target chunk size:** 400–800 tokens. Manuals have denser technical content; settings tables and feature descriptions benefit from larger context.
- **Overlap:** 0–50 tokens. Sections are semantically self-contained; less overlap needed.
- **Metadata:** `{manufacturer, model, section_path, page_number}`. Page number is critical for citation display.

#### Web articles (Premier Guitar)
- **Strategy:** scrape with `trafilatura` or `readability-lxml` to get clean main-content HTML, then paragraph-based chunking with a token budget.
- **Target chunk size:** 400–600 tokens.
- **Overlap:** 50 tokens.
- **Metadata:** `{url, title, author, published_at, section_heading}`. The URL is the citation anchor.

#### YouTube transcripts
- **Strategy:** **time-window + sentence-boundary**. Walk the transcript and accumulate sentences until the chunk crosses ~60 seconds *or* ~400 tokens, then close the chunk at the next sentence boundary. Record `start_seconds` and `end_seconds`.
- **Target chunk size:** 300–500 tokens.
- **Overlap:** 30 seconds OR 1 sentence — whichever is smaller. Transcripts are noisy; over-overlapping just adds duplicates.
- **Metadata:** `{video_id, title, start_seconds, end_seconds, channel}`. The `start_seconds` lets the UI deep-link to the exact moment (`https://youtube.com/watch?v=ID&t=Ns`).

### Token-count calibration

All "target chunk size" numbers above are **starting points, not gospel**. The right size depends on the embedding model's context window and the typical query length. **Phase 1 must include a calibration step:** ingest 2–3 representative documents, run 5–10 hand-picked queries, inspect retrieved chunks, and adjust. (Confidence: MEDIUM. The right way to validate is empirically against this specific corpus.)

### Unified chunk metadata schema

Every chunk, regardless of source, ends up with this row:

```sql
chunks (
  id                  UUID PRIMARY KEY,
  document_id         UUID REFERENCES documents(id),
  source_type         TEXT NOT NULL,
  chunk_index         INT NOT NULL,           -- ordinal within document
  text                TEXT NOT NULL,
  content_hash        TEXT NOT NULL UNIQUE,
  token_count         INT,
  embedding           VECTOR(N),              -- N depends on EMBEDDING_MODEL
  embedding_model     TEXT NOT NULL,
  -- source-type-specific fields (sparse, NULL when N/A)
  page_number         INT,                    -- manuals
  section_path        TEXT[],                 -- manuals
  start_seconds       INT,                    -- youtube
  end_seconds         INT,                    -- youtube
  url                 TEXT,                   -- articles
  -- generic
  metadata_json       JSONB,                  -- everything else
  created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX ON chunks (source_type);
CREATE INDEX ON chunks (document_id);
```

**Why sparse columns instead of putting everything in `metadata_json`:** the four fields above (page_number, section_path, timestamps, url) are needed for citation display on every retrieval. Putting them in JSONB forces JSON extraction on every read and prevents indexing. Everything else (channel name, author, etc.) lives in `metadata_json`.

---

## Retrieval Architecture

### Dense-only is sufficient for Phase 1, hybrid is a Phase 2+ improvement

At this corpus scale (<50K chunks) and with a curated corpus, **dense vector search alone will work well enough to ship**. Reasons:

- Modern embedding models (`text-embedding-3-large`, Voyage) handle the synonym problem (e.g., "warm tone" → "vintage", "crunchy") that BM25 famously misses.
- The cost of hybrid search is operational: maintaining a separate BM25 index (e.g., `tsvector` in Postgres), tuning fusion weights, debugging when results conflict. Premature complexity for a single-user tool.

**However**, dense search underperforms on **exact-string queries** that are common in this domain: model numbers (`TS-9`, `BD-2`, `JCM800`), knob names, specific song titles. For Phase 2, add a **Postgres `tsvector` full-text index** and fuse with Reciprocal Rank Fusion (RRF):

```python
# Phase 2 hybrid (sketch)
dense_hits  = vector_search(query_embedding, k=20)
sparse_hits = tsvector_search(query_string, k=20)
fused       = reciprocal_rank_fusion(dense_hits, sparse_hits, k=60)
return fused[:top_k]
```

Confidence: HIGH on the recommendation to defer hybrid; MEDIUM on the exact fusion approach.

### Reranking: skip in Phase 1

For <50K chunks with a curated source set, a cross-encoder reranker (Cohere Rerank, BGE-reranker) is overkill. The retrieved top-K from a good dense index will be high-quality. Reranking adds latency (extra API call or local model load) and cost.

**Add reranking only if** Phase 1 evaluation shows the relevant chunk is consistently in the top-20 but not top-5. That's the symptom rerankers fix. Until you see that symptom, you don't have the problem.

### Multi-query retrieval: yes, but as a Phase 2 quality lever

Generating 2–3 query rewrites with a fast LLM call (e.g., Haiku) before retrieval is one of the highest-ROI techniques for RAG in conversational settings, because user queries are short and ambiguous ("how do I get John Mayer's tone?" vs "what amp/pedal/guitar settings produce a clean blues tone with mids forward?"). However:

- It doubles or triples retrieval cost.
- It requires an extra round-trip before the main generation, adding 500ms–1s of latency.
- In Phase 1, the user is also the developer, so vague queries can be addressed by writing better queries.

**Build it as an opt-in flag in the retrieval module from day one** (`retrieve(query, multi_query=False)`), but default off in Phase 1. Turn it on in Phase 2 once you have a sense of which query types underperform.

### Source-type weighting: yes, lightweight

Different source types serve different purposes:

- **Manuals** are authoritative on *what a knob does* and *what settings are possible*.
- **Forum posts** are authoritative on *what real players try* for a given target tone.
- **Articles** sit in between — editorial recommendations.
- **YouTube transcripts** are noisy but capture demonstrations and ear-level descriptions.

For a tone-advice query, you probably want a mix. A simple approach: **retrieve top-K per source type, then merge**, rather than top-K across all sources. This guarantees the LLM sees both a manual snippet (grounded gear knowledge) and a forum snippet (player experience) for every answer.

```python
def retrieve(query_emb, total_k=12):
    return (
        vector_search(query_emb, where="source_type='manual'",  k=4) +
        vector_search(query_emb, where="source_type='forum'",   k=4) +
        vector_search(query_emb, where="source_type='article'", k=2) +
        vector_search(query_emb, where="source_type='youtube'", k=2)
    )
```

The exact ratios are a Phase 1 tuning target. (Confidence: MEDIUM — the principle is sound; the ratios are corpus-specific.)

### Top-K

For Claude's 200K context window, **K=10–15 chunks** is comfortable. Each chunk is ~500 tokens, so 12 chunks = ~6K tokens of context — leaving plenty of room for conversation history and the response. Start at **K=12** with the per-source split above. Tune after seeing real responses.

---

## Generation Architecture

### System prompt structure

The system prompt should be **rigid about role, citation, and refusal**:

```
You are a guitar tone advisor. You help a guitarist achieve specific sounds by
giving concrete, actionable recommendations: amp channel selection, EQ settings
(bass/mid/treble values 0–10), gain/drive levels, pedal selection and order,
guitar pickup selection, and playing technique notes.

GROUNDING RULES (these are non-negotiable):
1. Every concrete recommendation (specific gear, specific setting, specific
   technique) must be supported by at least one passage from <sources>.
2. Cite the supporting passage inline with [S{n}] where n is the source number.
3. If the user asks about gear or a tone that no source covers, say so plainly:
   "I don't have source material on that — I can only speak to what's in my
   corpus." Do NOT recommend gear based on general knowledge.
4. If sources conflict, surface the disagreement: "Source [S1] suggests X,
   [S3] suggests Y; the difference is...".
5. Distinguish between (a) settings a source explicitly recommends, and (b) your
   inference from a source. Hedge appropriately on (b).

FORMAT:
- Lead with a 1–2 sentence "what you're going for" summary.
- Then a bulleted signal-chain recommendation: guitar → pedals (in order) → amp.
- Then specific settings as a compact table or list.
- Inline citations throughout.
- End with one "things to try / vary" sentence.

The user's gear context is provided in the first user turn or in a <gear> block.
Trust it; do not ask for it again.
```

### Retrieved passage formatting

Inject sources as a structured block, **not** as a flat concatenation:

```xml
<sources>
<source id="S1" type="manual" doc="Boss BD-2" page="3" section="Controls">
[chunk text]
</source>
<source id="S2" type="forum" topic="bb_king_tone" post_index="2">
[chunk text]
</source>
<source id="S3" type="youtube" video="ABC123" start="142s">
[chunk text]
</source>
...
</sources>
```

Reasons:
- **Stable IDs (S1, S2...)** make `[S2]` citations machine-parseable in the response.
- **Type + provenance metadata** lets the model reason about source authority ("the manual says ..., though a forum poster reports ...").
- **XML over JSON** because Anthropic's models follow XML structure reliably and it's lighter on punctuation tokens.

The IDs `S1..Sn` are session-local — the `/sources/{chunk_id}` endpoint maps `S2` back to the actual `chunks.id` via a session-scoped lookup table that the API returns alongside the streamed answer (see the chat response schema below).

### Citation grounding enforcement

You cannot make a generative model 100% grounded with prompting alone. Defense in depth:

1. **Prompt** (above): explicit rules.
2. **Post-generation regex check:** every model number / specific setting in the response should be matchable against the retrieved chunks. If a gear name appears in the answer that isn't in any chunk, mark the response as "ungrounded" and surface that to the UI (a yellow banner: "model mentioned gear not in sources").
3. **Citation extraction validation:** parse `[S{n}]` markers from the response; if a marker references an `S{n}` that wasn't in the retrieved set, that's an error.
4. **Confidence: HIGH** that #1+#3 catches most issues. #2 (gear-name validation) is a Phase 2 hardening.

### Streaming: yes, from day one

Streaming responses is **not optional** for chat UX — a 3–5 second wait for a 400-token answer feels broken. The anthropic SDK's `messages.stream()` is straightforward; the FastAPI endpoint returns Server-Sent Events (SSE) or chunked text. Next.js can consume SSE natively via `EventSource` or the Vercel AI SDK.

**Citations are sent out-of-band, after the stream completes**, as a final JSON event:

```
event: token
data: "I'd recommend a Boss BD-2 [S1]..."

event: token
data: " with the gain at..."

...

event: citations
data: {"S1": {"chunk_id": "...", "doc": "Boss BD-2 Manual", "page": 3, ...}, ...}

event: done
data: {}
```

---

## Conversation Memory Architecture

### Session storage: in-process Python dict

Single-user, fully-local, per-session memory only — there is **no reason to use Redis or a database for session memory**. A plain dict keyed by `session_id` in the FastAPI process is correct:

```python
# server lifetime
sessions: dict[str, list[Message]] = {}
```

A new session starts when the UI sends `session_id=None`; the API returns a new UUID. Restarting the FastAPI process clears all sessions — that's an acceptable and expected behavior for a personal tool. Document it.

### History budget

For Claude's 200K context window and ~6K tokens of retrieved sources + ~1K system prompt, you can comfortably fit **the last 10–15 turn pairs** (20–30 messages) without truncation. Most chat sessions for tone advice will be much shorter (2–5 turns), so truncation will rarely fire.

### Truncation strategy when budget exceeded

A sliding window keeping the last N turn pairs is sufficient. Summarization-based memory (compress old turns into a summary) is **not worth the complexity** for this app:

- Sessions are short by nature.
- Tone advice is contextual to recent turns ("now make it less bright"), not to turn 1.

If a session ever does exceed budget, drop the oldest turn pair and continue. No summarization step.

### Gear context placement

The user's gear changes between sessions but not within a session. The natural placement:

**Gear lives in the first user message** as a structured `<gear>` block, and the system prompt explicitly says "trust the gear in <gear> for the whole conversation."

```
<gear>
- Guitar: Fender Stratocaster, single-coil pickups
- Amp: Vox AC30
- Pedals owned: Boss BD-2, MXR Phase 90, Strymon BlueSky
</gear>

How do I get a John Mayer-style clean tone?
```

**Why not the system prompt?** Because gear changes per session, and you don't want to mutate the system prompt mid-conversation (some prompt-caching strategies break if the system prompt isn't stable). Keeping it in the first user message is robust.

**Why not every turn?** Token waste, and the model handles "remember the user's gear from earlier" trivially within a single conversation.

The UI can render a "Edit gear" button that, when clicked, starts a new session — gear isn't intended to change mid-chat.

---

## FastAPI Endpoint Structure

### `POST /chat`

**Request:**
```json
{
  "session_id": "uuid-or-null",
  "message": "How do I get John Mayer's tone with my gear?",
  "gear": {                  // optional, only sent on first turn of a session
    "guitar": "Fender Strat",
    "amp": "Vox AC30",
    "pedals": ["BD-2", "Phase 90"]
  }
}
```

**Response:** SSE stream (see Generation Architecture above). The first event is `session` with the assigned `session_id` (so the UI can persist it for the next turn).

### `GET /sources/{chunk_id}`

Returns the full chunk + its parent document metadata, for the citation drawer in the UI:

```json
{
  "chunk_id": "...",
  "text": "Full chunk text...",
  "source_type": "manual",
  "document": {
    "title": "Boss BD-2 Manual",
    "manufacturer": "Boss",
    "model": "BD-2"
  },
  "page_number": 3,
  "section_path": ["Controls", "Tone Section"],
  "url": null,
  "neighbor_chunks": [...]   // optional: prev/next chunk in same doc, for context
}
```

`neighbor_chunks` is a nice-to-have for letting the user expand context around a citation. Phase 2.

### `GET /health`

Standard. Returns `{"status": "ok", "db": "ok", "embedding_model": "..."}`.

### `GET /ingest/status`

Reads from `ingest_runs` and `chunks`:
```json
{
  "embedding_model": "text-embedding-3-large",
  "last_run": {"finished_at": "...", "status": "completed"},
  "n_documents": 48,
  "n_chunks": 1247,
  "by_source_type": {"forum": 102, "manual": 743, "article": 187, "youtube": 215}
}
```

### `DELETE /sessions/{session_id}` (Phase 1.5)

For "new chat" button. Removes the in-memory entry. Optional in Phase 1 — UI can just generate a fresh `session_id` and ignore the old one (the old session will be garbage-collected on server restart anyway).

---

## Build Order (Vertical MVP)

### Guiding principle

**Phase 1 ships an end-to-end working system on the *narrowest possible slice* of the corpus**, proving the architecture works before scaling up. The most risky integration is "raw text → embeddings → vector search → grounded answer." Validate that loop first; expand sources second.

### Phase 1: Vertical slice — forum posts only

Goal: type a question, get a cited answer, end-to-end.

1. **Schema:** create `documents`, `chunks`, `ingest_runs` tables. Confirm pgvector extension installed and a `vector(N)` column works.
2. **Loader: forum posts only.** Simplest format (plain .txt). Defer PDF, web, YouTube.
3. **Chunker: paragraph-based with token budget.** Skip source-type dispatch — only forum exists in Phase 1.
4. **Embedder: OpenAI `text-embedding-3-small`** (cheapest; sized for fast iteration). The `EMBEDDING_MODEL` env var indirection is in place but the only implementation is OpenAI.
5. **Writer: psycopg2 upsert with content-hash dedup.** Idempotent re-runs work.
6. **Retrieval: dense-only, no source weighting, K=8.** Simplest possible.
7. **Generation: anthropic SDK, streaming, system prompt with citation rules.** Non-negotiable from day one — citation grounding is the product.
8. **FastAPI: `/chat` (streaming SSE) + `/sources/{chunk_id}` + `/health` + `/ingest/status`.**
9. **Next.js: minimal chat UI** — input box, message list, citation pill that opens a drawer with the source chunk. Streaming token rendering.
10. **Session memory: in-process dict, sliding window.**

**Exit criterion for Phase 1:** "Ask 'What amp settings did BB King use?' → get a streamed answer with at least one `[S1]` citation that, when clicked, shows the actual forum post text."

### What's deferred from Phase 1 (and why each is safely deferred)

| Component | Deferred to | Why safe to defer |
|---|---|---|
| PDF ingestion (manuals) | Phase 2 | PDF parsing is the highest-effort loader; forum posts prove the loop. |
| Article scraping | Phase 2 | Adds a network-fetch + HTML-cleaning dependency. Not needed to prove the loop. |
| YouTube transcripts | Phase 2 | Requires `youtube-transcript-api` and time-window chunking. Not needed to prove the loop. |
| Source-type weighting | Phase 2 | Only meaningful once >1 source type exists. |
| Hybrid (BM25) retrieval | Phase 3 | Only worth adding if dense retrieval underperforms on exact-name queries. |
| Multi-query rewriting | Phase 3 | Quality lever; not needed for first working version. |
| Reranking | Phase 3+ | Only add if Phase 1–2 evaluation shows a top-K-but-not-top-5 problem. |
| Embedding model swap (Voyage) | Phase 2 | Env-var plumbing is in place from Phase 1; adding the Voyage client implementation comes when comparing quality. |
| Post-gen gear-name validation | Phase 3 | Grounding via prompt + citation parsing covers most cases; gear-name regex is a hardening step. |
| Conversation summarization | Out of scope | Sessions are too short to need it. |

### Phase 2: corpus expansion

Add the three remaining loaders (PDF, article, YouTube). Each can ship independently:
- Add `PDFLoader` + `SectionAwareChunker` for manuals. Re-run ingest.
- Add `ArticleLoader` (trafilatura) + paragraph chunker. Re-run ingest.
- Add `YouTubeLoader` + time-window chunker. Re-run ingest.

Add source-type weighting in retrieval once all four types exist.

### Phase 3: quality

- Hybrid retrieval (add tsvector index, RRF fusion).
- Multi-query rewriting (Haiku-based).
- Evaluation harness: a `goldens.jsonl` of (query, expected-cited-sources) pairs. Run before/after each retrieval change.
- Embedding model comparison (Voyage vs OpenAI on goldens).

### Risks to validate first (Phase 1 must touch each)

1. **pgvector dimension match across models.** If `EMBEDDING_MODEL` changes dimension, `vector(N)` column won't accept it. Decision: store dimension in a per-row column OR maintain separate tables per model. Phase 1 should validate this matters by trying a re-embed.
2. **Citation grounding behavior under streaming.** Test that the model produces `[S{n}]` markers correctly mid-stream and that out-of-band citation payload arrives reliably.
3. **psycopg2 + pgvector ergonomics.** Confirm the `pgvector.psycopg2` adapter handles numpy arrays cleanly; debug serialization issues now, not later.
4. **Session memory across page reloads.** The UI must persist `session_id` in `localStorage`; the API must tolerate `session_id` referring to a session lost on server restart (fall back to creating a new session, don't 500).

---

## Component Boundaries Summary

| Component | Input | Output | Depends on | Built in |
|---|---|---|---|---|
| Loader | filesystem path or URL | `RawDocument` | — | Phase 1 (forum only) |
| Normalizer | `RawDocument` | `NormalizedDocument` (plain text + metadata) | Loader | Phase 1 |
| Chunker | `NormalizedDocument` | `list[Chunk]` (text + source-specific metadata) | Normalizer | Phase 1 |
| Embedder | `list[Chunk]` | `list[Chunk]` with `embedding` populated | Chunker, embedding provider | Phase 1 |
| Writer | `list[Chunk]` | DB rows | Embedder, Postgres | Phase 1 |
| Retriever | query string + filters | `list[RetrievedChunk]` | DB, Embedder (query encoding) | Phase 1 |
| Prompt builder | query + history + retrieved chunks + gear | anthropic `messages` array | Retriever, Session store | Phase 1 |
| Generator | `messages` array | streamed tokens + final citations | Prompt builder, anthropic SDK | Phase 1 |
| Session store | session_id, message | updated history | — (in-process) | Phase 1 |
| API layer | HTTP | SSE / JSON | All above | Phase 1 |
| UI | user input | rendered tokens + clickable citations | API | Phase 1 |

The **one-way data flow** (filesystem → store → API → UI) and the **store as the only ingestion↔serving boundary** are the two structural decisions that everything else hangs off of.

---

## Sources & Confidence

- **PROJECT.md** (project requirements, constraints, corpus inventory): HIGH confidence, primary source.
- **Filesystem inspection of `raw_data/`**: HIGH confidence on corpus size (48 source documents).
- **RAG architecture patterns** (offline ingestion vs online serving, content-hash dedup, source-type metadata, streaming with out-of-band citations, in-process session memory for single-user tools): HIGH confidence — these are well-established patterns across the RAG literature and production deployments.
- **Specific chunk sizes / top-K values**: MEDIUM confidence. The ranges given are reasonable starting points but require Phase 1 calibration on this specific corpus. Flagged inline where this matters.
- **Skipping reranking / hybrid / multi-query in Phase 1**: HIGH confidence given the corpus size and single-user context. These are correct deferrals.
- **Web search was unavailable** for this research run, so no live-source URLs are cited. All recommendations trace to training-data knowledge of established RAG patterns plus inspection of the project's own corpus and requirements.

---
*Researched: 2026-05-13*
