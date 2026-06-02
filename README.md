# Guitar Tone Advisor

A personal conversational RAG app that answers "how do I sound like X?" questions with concrete, cited recommendations — specific amp settings, pedal choices, signal chain order, and knob positions — drawn from a curated corpus of forum discussions, equipment manuals, Premier Guitar articles, and YouTube transcripts.

**No vague advice. No hallucinated gear. Every answer traces back to a real source.**

---

## What it does

You describe your current rig and a target tone. The app retrieves the most relevant passages from its corpus, feeds them to Claude as grounding context, and streams back a response with inline citations like `[S1]`, `[S3]`. Click a citation to see the exact excerpt that informed it.

Example prompts:
- *"I have a Fender Deluxe Reverb and a TS9. How do I get close to BB King's tone?"*
- *"My setup is a Les Paul into a JCM800. What's the Mark Knopfler clean sound?"*
- *"I want that EVH brown sound. I have a 5150."*

---

## Architecture

One-way data flow, no framework abstractions:

```
raw_data/ ──► ingestion CLI ──► PostgreSQL/pgvector ──► FastAPI ──► SSE ──► Next.js
              (offline, once)    (chunks + vectors)     (chat API)          (chat UI)
```

- **Ingestion** is an offline CLI (`python -m app.ingest.pipeline`) — not an API. Run it once to seed the database; re-runs are safe via content-hash dedup.
- **Retrieval** uses HNSW cosine similarity on 1536-d OpenAI embeddings, with gear alias expansion (Strat → Stratocaster, JCM800 → Marshall JCM800, etc.) applied before query embedding.
- **Generation** calls Claude via the Anthropic SDK. Sources are injected as a `<sources>` XML block; citations are extracted from the response stream and sent as a separate SSE event after the token stream completes.
- **No LangChain. No LlamaIndex.** Chunking, embedding, retrieval, and generation are all raw Python.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI 0.136 + uvicorn (ASGI) |
| LLM | Anthropic SDK (`claude-sonnet-*`) |
| Embeddings | OpenAI `text-embedding-3-small` (1536-d, configurable via `EMBEDDING_MODEL`) |
| Vector DB | PostgreSQL + pgvector (HNSW index, cosine distance) |
| PDF parsing | pymupdf4llm (primary) → pypdf (fallback) |
| Web scraping | trafilatura |
| YouTube | youtube-transcript-api + yt-dlp fallback |
| SSE streaming | sse-starlette |
| Frontend | Next.js (App Router, TypeScript, Tailwind) |

---

## Corpus

The knowledge base lives in `raw_data/` and is committed to the repo:

| Source | Contents |
|--------|----------|
| `forum_posts/` | 10 curated forum Q&A threads — BB King, EVH, Mark Knopfler, John Mayer, SRV, funk, lo-fi, neo-soul, pop-punk, and more |
| `manuals/` | 15 amp and pedal PDFs — Marshall JCM800/JTM45, Fender Deluxe Reverb/Twin Reverb, Vox AC30, Mesa Boogie Mark V, Orange Rockerverb, Blackstar HT5, Boss BD-2/DD-3/DS-1, EHX Big Muff, Ibanez TS9, MXR Phase 90, Strymon BlueSky |
| `article_urls.txt` | 10 Premier Guitar article URLs on tone, gear, and mods |
| `youtube_ids.txt` | 13 YouTube video IDs on artist and genre tones |

---

## Setup

### Prerequisites

- Python 3.12+
- Node.js 22+
- Docker (for PostgreSQL + pgvector)
- An OpenAI API key (embeddings)
- An Anthropic API key (chat generation)

### 1. Start the database

```bash
docker-compose up -d
```

### 2. Create the schema

```bash
cp .env.example .env   # fill in DATABASE_URL, OPENAI_API_KEY, ANTHROPIC_API_KEY
python -m app.db.init_db
```

### 3. Set up the Python environment

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Ingest the corpus

```bash
python -m app.ingest.pipeline
```

This embeds all forum posts, PDF manuals, articles, and YouTube transcripts into pgvector. Takes a few minutes on first run. Re-running is safe — already-embedded chunks are skipped.

### 5. Start the backend

```bash
uvicorn app.main:app --reload
```

### 6. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## Development

```bash
# Run all offline tests (no DB or API keys needed)
venv/bin/python -m pytest tests/ -x -v

# Run with live DB tests
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/guitar_tone_advisor \
  venv/bin/python -m pytest tests/ -x -v

# Check retrieval quality against the held-out eval set
python -m app.eval.retrieval --held-out

# Run faithfulness eval
python -m app.eval.ragas
```

---

## Project layout

```
app/
  ingest/       # loader, chunker, embedder, writer, pipeline CLI
  retrieval/    # HNSW similarity search + gear alias expansion
  generation/   # prompt builder, Claude streaming, citation extraction
  eval/         # retrieval recall scorer, RAGAS faithfulness scorer
  main.py       # FastAPI app (chat endpoint, sources endpoint)
frontend/       # Next.js chat UI
raw_data/       # committed corpus (forum posts, PDFs, URLs, video IDs)
eval/           # golden eval set + held-out tuples
tests/          # pytest suite (offline + live-DB)
```

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `OPENAI_API_KEY` | Yes | — | Used for embeddings |
| `ANTHROPIC_API_KEY` | Yes | — | Used for chat generation |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | Swap to `text-embedding-3-large` or `voyage-*` without code changes |

---

## Design constraints

- **Single user, fully local** — no auth, no multi-tenancy, no cloud hosting
- **Citation grounding is mandatory** — responses that cannot cite a source passage are refused
- **No framework abstractions** — this is a learning project; the RAG pipeline is built from scratch so the internals are visible
