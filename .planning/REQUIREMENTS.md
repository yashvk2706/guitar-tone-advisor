# Requirements: Guitar Tone Advisor

**Defined:** 2026-05-15
**Core Value:** Given a user's gear and a target tone, produce concrete, cited settings recommendations they can immediately act on — no vague advice, no hallucinated gear.

## v1 Requirements

### Corpus Ingestion

- [ ] **INGEST-01**: User can run a CLI command that loads all forum post `.txt` files from `raw_data/forum_posts/` into the database
- [ ] **INGEST-02**: Each forum post is split into semantically coherent chunks with source metadata attached (source_type, source_name, chunk_index, content_hash)
- [x] **INGEST-03**: Chunks are embedded using the model configured via `EMBEDDING_MODEL` env var (default: `text-embedding-3-small`)
- [x] **INGEST-04**: Embeddings and chunk text are stored in PostgreSQL with the `pgvector` extension (`chunks` table, `vector(1536)` column)
- [x] **INGEST-05**: An HNSW index on cosine distance is created and maintained for efficient approximate nearest-neighbor retrieval
- [ ] **INGEST-06**: Re-running ingestion is idempotent — content-hash deduplication skips unchanged chunks; only changed/new chunks are re-embedded
- [ ] **INGEST-07**: A `gear_aliases.json` file maps gear shortforms to canonical names (e.g., `TS9 ↔ Ibanez Tube Screamer`, `Strat ↔ Stratocaster`) and bidirectional alias expansion is applied to user queries before embedding

### Retrieval

- [ ] **RETR-01**: Given a user tone query, the system retrieves the top-K most relevant chunks via HNSW cosine similarity search
- [ ] **RETR-02**: User query is expanded using gear aliases before embedding (both shortforms and full names searched)
- [ ] **RETR-03**: Retrieved chunks include full source metadata (source_type, source_name, page/chunk reference) passed to the generation layer

### Generation

- [ ] **GEN-01**: Claude generates tone recommendations drawing only from retrieved passages — not from training knowledge
- [ ] **GEN-02**: Responses include inline `[S1]`, `[S2]`, ... citations attached to specific claims (not appended as footnotes)
- [ ] **GEN-03**: Responses include concrete knob positions on a 0–10 scale (e.g., Bass=7, Mid=4, Treble=6) when the corpus supports it
- [ ] **GEN-04**: Responses include signal chain order (e.g., Guitar → Wah → OD → Amp) when relevant to the query
- [ ] **GEN-05**: When the user's described gear differs from the corpus gear, Claude performs inline gear translation ("You have a Boss Katana — here's how to approximate this on it")
- [ ] **GEN-06**: When the corpus lacks sufficient material for a query, Claude refuses with a reason rather than hallucinating ("I don't have material on Friedman amps — closest is the Marshall JCM800, want that instead?")
- [ ] **GEN-07**: Responses stream token-by-token to the frontend via SSE; citations are sent as a separate out-of-band payload after the stream completes

### Chat & Conversation

- [ ] **CHAT-01**: User can type a gear description + target tone in natural language and receive a grounded recommendation
- [ ] **CHAT-02**: Per-session conversation history is maintained (in-process; cleared on server restart or new chat)
- [ ] **CHAT-03**: User can start a new session via a "New chat" button that clears conversation history
- [ ] **CHAT-04**: Three suggested follow-up action buttons appear under each answer ("Cleaner?", "Live setting?", "Budget version?")

### Citations & Grounding

- [ ] **CITE-01**: Each `[Sn]` citation in the response is clickable and opens an expandable drawer showing the raw chunk text and source name
- [ ] **CITE-02**: Each citation displays a source-type label: `[Forum]`, `[Manual]`, `[Article]`, or `[YouTube]`
- [ ] **CITE-03**: Each answer displays a corpus coverage indicator showing how many distinct sources support the recommendation (e.g., "3 sources agree")

### UI

- [ ] **UI-01**: Chat responses render Markdown (bold, lists, code blocks) correctly in the browser
- [ ] **UI-02**: Full conversation history for the current session is visible and scrollable
- [ ] **UI-03**: User can copy the recommendation block (amp/pedal settings section) to clipboard with one click
- [ ] **UI-04**: A loading/progress indicator shows state transitions ("Searching corpus..." → "Drafting...") while waiting for a response
- [ ] **UI-05**: When a response contains amp/pedal settings (e.g. Bass=7, Mid=4, Treble=6), render them as visual rotary knob components turned to the correct position with the value labeled beneath

### Evaluation

- [ ] **EVAL-01**: A golden eval set of ≥20 (query, expected-chunk-ids, expected-themes) tuples is built from the 10 forum-post topics, with a held-out subset written before any retrieval tuning begins
- [ ] **EVAL-02**: Recall@K and MRR are computed against the golden eval set and logged after each retrieval configuration change
- [ ] **EVAL-03**: An empty-context smoke test verifies the model produces a refusal (not a hallucinated answer) when zero chunks are retrieved
- [ ] **EVAL-04**: RAGAS faithfulness scoring is computed on a sample of generated answers to measure the hallucination rate (claims in the answer not supported by retrieved chunks)

## v2 Requirements

### Corpus Expansion (Phase 2)

- **INGEST-08**: Ingestion pipeline processes PDF equipment manuals from `raw_data/manuals/` (15 PDFs: amps and pedals) with section-aware chunking that never splits inside a table
- **INGEST-09**: Ingestion pipeline scrapes and extracts text from the 10 Premier Guitar article URLs in `raw_data/article_urls.txt` with rate-limiting and paywall detection
- **INGEST-10**: Ingestion pipeline fetches and processes transcripts for the 13 YouTube video IDs in `raw_data/youtube_ids.txt` with time-window chunking and auto-caption quality tagging
- **RETR-04**: Retrieval weights source types differently (e.g., manual chunks up-weighted for technical spec queries; forum chunks up-weighted for tone-feel queries)

### Retrieval Quality (Phase 3)

- **RETR-05**: Hybrid retrieval combines HNSW dense vector search with Postgres `tsvector` full-text search, fused via Reciprocal Rank Fusion (RRF)
- **RETR-06**: Multi-query rewriting (Claude Haiku) generates 3 query variants before retrieval to improve recall for abstract or ambiguous queries
- **RETR-07**: Voyage AI embedding model is implemented behind the `Embedder` Protocol and benchmarked against OpenAI embeddings using the golden eval set

### UI (Phase 4)

- **UI-06**: Side-panel sources view shows all retrieved chunks for a given answer in a two-pane layout
- **UI-07**: "Why?" toggle on each setting surfaces the source passage that motivated that specific recommendation

## Out of Scope

| Feature | Reason |
|---|---|
| LangChain / LlamaIndex in retrieval path | Explicit project constraint — learning RAG internals is the point |
| Persistent user accounts / auth | Personal single-user tool |
| Persistent chat history across sessions | Session-scoped only; no DB-backed session store |
| Explicit gear inventory database | User describes gear per session; persistent profile is v3+ |
| Multi-user / multi-tenancy | Out of scope for personal tool |
| Mobile / native app | Web-first, defer indefinitely |
| External hosting / cloud deployment | Fully local |
| Audio file upload / waveform analysis | Different product |
| Real-time collaboration | Not applicable |
| Thumbs-up/down feedback UI | Useless without a training loop |
| Confidence as a percentage ("87% sure") | Fake precision; use coarse indicators tied to chunk counts |
| Recommending gear the user doesn't own as primary recommendation | Gear translation required; unowned gear is a fallback only |

## Traceability

_Populated during roadmap creation 2026-05-15. Revised 2026-05-15: EVAL-01 moved to Phase 1 so the golden eval set is locked before any retrieval tuning._

| Requirement | Phase | Status |
|---|---|---|
| INGEST-01 | Phase 1 | Pending |
| INGEST-02 | Phase 1 | Pending |
| INGEST-03 | Phase 1 | Complete |
| INGEST-04 | Phase 1 | Complete |
| INGEST-05 | Phase 1 | Complete |
| INGEST-06 | Phase 1 | Pending |
| INGEST-07 | Phase 2 | Pending |
| RETR-01 | Phase 2 | Pending |
| RETR-02 | Phase 2 | Pending |
| RETR-03 | Phase 2 | Pending |
| GEN-01 | Phase 3 | Pending |
| GEN-02 | Phase 3 | Pending |
| GEN-03 | Phase 3 | Pending |
| GEN-04 | Phase 3 | Pending |
| GEN-05 | Phase 3 | Pending |
| GEN-06 | Phase 3 | Pending |
| GEN-07 | Phase 3 | Pending |
| CHAT-01 | Phase 3 | Pending |
| CHAT-02 | Phase 3 | Pending |
| CHAT-03 | Phase 3 | Pending |
| CHAT-04 | Phase 4 | Pending |
| CITE-01 | Phase 3 | Pending |
| CITE-02 | Phase 3 | Pending |
| CITE-03 | Phase 3 | Pending |
| UI-01 | Phase 4 | Pending |
| UI-02 | Phase 4 | Pending |
| UI-03 | Phase 4 | Pending |
| UI-04 | Phase 4 | Pending |
| UI-05 | Phase 4 | Pending |
| EVAL-01 | Phase 1 | Pending |
| EVAL-02 | Phase 5 | Pending |
| EVAL-03 | Phase 5 | Pending |
| EVAL-04 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 33 total
- Mapped to phases: 33 (100%) ✓
- Unmapped: 0

---
*Requirements defined: 2026-05-15*
*Last updated: 2026-05-15 — EVAL-01 reassigned from Phase 5 to Phase 1 (final plan) so the held-out golden eval set is written before any retrieval tuning.*
