# Research Summary: Guitar Tone Advisor

## TL;DR

- **Strict offline/online split.** Ingestion is a CLI that writes to Postgres; FastAPI is a thin read-only retrieval+generation server. The pgvector store is the only boundary between the two halves — this is the most important architectural decision.
- **Phase 1 is a forum-only vertical slice.** Plain `.txt` ingestion -> OpenAI embeddings -> HNSW vector search -> Claude streaming with inline `[S{n}]` citations -> minimal Next.js chat. Defer PDFs, articles, YouTube to Phase 2 — they are loader complexity, not loop complexity.
- **The product lives or dies on grounding.** The model will silently fall back to its pretraining opinions about Marshalls and Stratocasters when retrieval is weak. Citation enforcement (prompt + post-gen validation + empty-context smoke test) is non-negotiable from day one.
- **Dense-only retrieval is enough for Phase 1, but barely.** Gear shortforms (`TS9`, `JCM800`, `EVH`) and numeric settings ("Treble at 7") are the two known weak spots. Plan to add `tsvector` hybrid retrieval in Phase 2 — it is not optional for this domain long-term.

## Confirmed Stack

All versions verified live against PyPI on 2026-05-13. Python 3.12 recommended.

| Component | Library | Version | Notes |
|---|---|---|---|
| Web framework | FastAPI | 0.136.1 | Async, ASGI |
| ASGI server | uvicorn[standard] | 0.46.0 | Dev + local prod |
| SSE streaming | sse-starlette | 3.4.4 | For streaming Claude tokens |
| Settings | pydantic-settings + python-dotenv | 2.14.1 / 1.2.2 | `EMBEDDING_MODEL` env-driven |
| Postgres driver | psycopg[binary] | 3.3.4 | **v3, not v2** — better pgvector support, sync+async on one conn |
| pgvector client | pgvector | 0.4.2 | Use `register_vector(conn)` per pool conn |
| LLM SDK | anthropic | 0.102.0 | Claude Sonnet 4.5 via `messages.stream()` |
| Default embeddings | openai | 2.36.0 | `text-embedding-3-small` (1536-d) is v1 default |
| Optional embeddings | voyageai | 0.3.7 | For Phase 3 model comparison |
| Local fallback embeddings | sentence-transformers | 5.5.0 | `BAAI/bge-small-en-v1.5` for offline dev |
| PDF (primary) | pypdf | 6.11.0 | BSD-3, fast, for clean born-digital manuals |
| PDF (escalation) | PyMuPDF + pymupdf4llm | 1.27.2.3 | AGPL — OK for local-only personal app. Markdown-with-tables output |
| Article extraction | trafilatura | 2.0.0 | Boilerplate-aware; outputs Markdown directly |
| HTTP client | httpx | 0.28.1 | Explicit timeouts/retries |
| YouTube transcripts | youtube-transcript-api | 1.2.4 | Primary; pin version (history of YT-induced breakage) |
| YouTube fallback | yt-dlp | 2026.3.17 | Subtitle extraction when API blocked |
| Retry/backoff | tenacity | 9.1.4 | Wrap every external API call |
| Token counting | tiktoken | 0.12.0 | `cl100k_base` encoder for OpenAI sizing |
| HTML escape hatch | beautifulsoup4 | 4.14.3 | Only when trafilatura fails |

**Frontend:** Next.js (existing project assumption) with rewrites proxying `/api/py/*` to `localhost:8000` — no CORS needed in dev.

**Explicit non-deps:** LangChain, LlamaIndex, langchain-text-splitters, newspaper3k (abandoned), unstructured (multi-GB), marker-pdf (GPU), docling, chromadb, qdrant. The point of this project is to learn RAG without framework magic.

## Feature Scope

### Table Stakes (v1)

**Chat & conversation**
- Single-turn tone query -> cited answer
- Per-session multi-turn context (gear + target reused across turns)
- Visible retrieval / generation state ("searching corpus..." -> "drafting...")
- "New chat" button clears session

**Citation & grounding** (the product's core promise — the most important UX)
- **Inline citations attached to specific claims**, not dumped at the end
- Source-type label on every citation: `[Forum]` `[Manual]` `[Article]` `[YouTube]`
- Expandable source preview (3–5 sentences + source name + page/timestamp)
- Refusal-with-reason when corpus is sparse ("I don't have material on Friedman amps — closest is Marshall JCM800, want that instead?")

**Gear & tone input**
- Free-text gear description in chat (no profile, no form)
- Artist name + genre + free-text descriptors all accepted as natural language
- "Closest you can get with your gear" framing (LLM-handled inline in v1)

**Answer quality**
- Concrete knob positions on 0–10 scale when corpus supports
- Signal chain order in output
- Pedal-to-amp pairing logic in answer text

**UI**
- Markdown rendering for list-shaped answers
- Session history visible
- Copy-to-clipboard on the recommendation block

**Two v1 differentiators (cheap, high-leverage):**
- Suggested follow-ups under each answer (3 buttons: "How do I get this cleaner?" / "What if I'm playing live?" / "Budget version?")
- Source diversity indicator ("3 forum posts, 1 manual agree")

### Deferred (v2)

- All non-forum loaders: PDF manuals, Premier Guitar articles, YouTube transcripts
- Source-type weighting in retrieval (meaningless until >1 source type exists)
- Hybrid retrieval (BM25 / tsvector + RRF fusion) — Phase 3
- Multi-query rewriting via Haiku — Phase 3
- Reranking (Cohere/BGE) — only if eval shows top-K-but-not-top-5 problem
- Voyage AI embedding model swap — env-var plumbing in v1, implementation in Phase 3
- Quote-level (span) citation grounding
- Inferred gear normalization as an explicit layer
- Visual signal-chain diagram
- Side-panel cited-passages two-pane view
- Conflicting-sources surfacing
- "Compare two answers" mode (diagnostic)
- "Why" toggle on each setting
- Bedroom/band/studio context toggle
- Reference-track citation
- Persistent "current rig" pill

### Anti-Features

- **Persistent gear profile / accounts** — explicitly out of scope per PROJECT.md
- **Generic "ask me anything about guitar"** — pulls the product toward Wikipedia, away from actionable settings
- **Hallucinated knob settings** — must NOT invent "Bass=5, Mid=5, Treble=5" when corpus is silent
- **Recommending gear the user doesn't own** as the primary recommendation
- **Audio file upload / waveform analysis** — different product
- **Inline YouTube embeds** — linked timestamp is enough
- **Confidence as a percentage** ("87% sure") — fake precision; use coarse labels tied to actual chunk counts
- **Thumbs-up/-down feedback UI** — useless without a training loop
- **LangChain / LlamaIndex** in the retrieval path — entire point is to not have them

## Architecture: What's Decided

**These are locked. Planners do not re-litigate.**

1. **Ingestion is a CLI (`python -m app.ingest.pipeline`), not an API endpoint.** Different runtime profile, different failure mode, different access pattern from chat. A read-only `/ingest/status` endpoint reads from `ingest_runs` for the UI; it does not trigger ingestion.

2. **One-way data flow: raw -> ingestion -> pgvector -> API -> UI.** UI never writes to the store; ingestion never reads session memory. Postgres is the only ingestion<->serving boundary.

3. **Postgres + pgvector, single Postgres instance, local.** No second vector store. No Redis. No object store.

4. **psycopg v3 (`psycopg[binary]==3.3.4`)**, not psycopg2. PROJECT.md mentions psycopg2; psycopg3 supersedes it with first-class pgvector support and is the explicit decision.

5. **HNSW index, not IVFFlat.** Corpus is <50K chunks; HNSW gives better recall out-of-the-box, works on an empty table (IVFFlat does not), and needs no `lists` tuning. Parameters: `m=16, ef_construction=64`.

6. **Cosine distance (`<=>` operator, `vector_cosine_ops` index).** OpenAI and Voyage embeddings are unit-normalized. Don't mix operators.

7. **Single `embedding vector(1536)` column with an `embedding_model` text column alongside.** Dimension is fixed at column-create time; swapping models means re-ingesting. Retrieval filters by `WHERE embedding_model = $1` defensively.

8. **Embedding access goes through an `Embedder` Protocol** with `embed_documents()` / `embed_query()` split. The retrieval code never imports `openai` or `voyageai` directly. Factory dispatches on `EMBEDDING_MODEL` env var. The two-method split is what makes Voyage's asymmetric document/query encoding work without leaking provider concerns.

9. **Chunking dispatches on `source_type`.** No universal chunker.
   - Forum posts: one post = one chunk if <=1200 tokens; otherwise paragraph-pack to ~800 tokens, no overlap. Strip quoted reply blocks.
   - PDF manuals: `pymupdf4llm.to_markdown()` -> split on `## ` / `### ` headings -> 400–800 tokens with 50–80 token overlap. **Never split inside a table.**
   - Articles: trafilatura Markdown -> heading-then-paragraph-pack, ~500 tokens, 80 overlap.
   - YouTube: 60-second sliding windows with 10-second overlap. Store `timestamp_sec` per chunk. Mark `is_auto_generated`.

10. **Content-hash dedup is the primary idempotency mechanism.** `sha256(normalized_text + source_id + chunk_index)` is the chunk's natural key. Re-running ingestion is safe; only changed chunks get re-embedded. `--full-rebuild` flag is the escape hatch.

11. **Session memory is an in-process Python dict** keyed by `session_id`. No Redis, no DB. Server restart clears sessions — that is acceptable for a single-user tool. Document it.

12. **Gear context lives in the first user message** as a `<gear>` block, not in the system prompt (system prompt stays stable for prompt-caching), not repeated every turn (token waste).

13. **Streaming from day one** via SSE with `sse-starlette`. Citations sent out-of-band as a final `event: citations` JSON payload after the token stream completes. A 3–5 second wait for a 400-token answer feels broken.

14. **Sources injected as XML-structured `<sources>` block** with stable session-local IDs (`S1..Sn`), not as flat concatenation. Anthropic models follow XML reliably; XML is lighter on punctuation tokens than JSON.

15. **Direct retrieval, not Claude tool-calls, in v1.** Tool-calling-based retrieval is a v2 feature once telemetry exists.

16. **Local dev: Next.js rewrites proxy `/api/py/*` to `localhost:8000`.** No CORS configuration. Mirrors a production reverse-proxy topology.

## Phase 1 Vertical MVP Cut

**The narrowest possible slice that proves the architecture works end-to-end.** The risky integration is "raw text -> embeddings -> vector search -> grounded answer with citations." Validate that loop first; scale the corpus second.

### What Phase 1 ships

1. **Schema migration:** `documents`, `chunks`, `ingest_runs` tables. `vector` extension confirmed. Single `chunks_embedding_hnsw_cos` HNSW index. `pg_trgm` extension installed (unused in Phase 1, present for Phase 2 hybrid).
2. **Loader: forum posts only.** Plain `.txt` in `raw_data/forum_posts/`. Simplest format; defers all PDF/HTML/YouTube complexity.
3. **Chunker:** post-aware splitting; quoted reply blocks stripped; ~300–800 tokens with 50-token overlap when posts are long. No source-type dispatch yet — only forum exists.
4. **Embedder:** `OpenAIEmbedder` via the Protocol, model `text-embedding-3-small` (1536-d). Factory + env var indirection is in place even though only one implementation exists, so Phase 3 swap is friction-free.
5. **Writer:** psycopg3 upsert with content-hash dedup; idempotent re-runs.
6. **Retrieval:** dense-only, no source weighting, `K=8`, cosine, HNSW. `register_vector(conn)` once per pool connection.
7. **Generation:** anthropic SDK streaming, `claude-sonnet-4-5` (or current equivalent), temperature 0.0–0.2, rigid system prompt with worked refusal example, `<sources>` XML block, `[S{n}]` citation format.
8. **FastAPI endpoints:** `POST /chat` (SSE), `GET /sources/{chunk_id}`, `GET /health`, `GET /ingest/status`.
9. **Next.js minimal chat UI:** input box, message list, streaming token rendering, clickable citation pill that opens a drawer with the chunk text.
10. **Session memory:** in-process dict, sliding window (drop oldest turn pair when over budget — no summarization).
11. **Golden eval set (>=20 query/expected-chunk tuples)** built from the 10 forum-post topics, with recall@K and MRR scoring. This starts at the end of Phase 1, before any tuning.
12. **Empty-context and wrong-context smoke tests** that verify the model refuses rather than confabulates.

### What is explicitly NOT in Phase 1

- PDF ingestion (manuals) — Phase 2
- Article scraping — Phase 2
- YouTube transcripts — Phase 2
- Source-type weighting in retrieval — Phase 2 (needs >1 source type)
- Hybrid (tsvector + RRF) retrieval — Phase 3
- Multi-query rewriting — Phase 3
- Reranking — Phase 3+, only if eval reveals the symptom
- Voyage embedder implementation — Phase 3 (factory dispatch is in place)
- Post-generation gear-name regex validation — Phase 3 hardening
- Conversation summarization — never (sessions too short)
- Visual signal-chain diagram, side-panel sources view, compare-two-answers — v2

### Exit criterion for Phase 1

> *"Ask 'What amp settings did BB King use?' — get a streamed answer with at least one `[S1]` citation that, when clicked, opens a drawer showing the actual forum post text. The same query asked with `retrieved_chunks=[]` produces a refusal, not an answer."*

## Top 3 Phase-1 Risks

| Risk | Warning Sign | Mitigation |
|---|---|---|
| **Model fabricates settings from pretraining instead of corpus.** Highest-stakes failure in the project; collapses the entire value proposition. Most acute in Phase 1 because the corpus is small (10 forum posts), so many queries will land on weak retrievals. | Answers contain knob values not present in any cited chunk; answers look identical with real vs empty context; confident phrasing like "a classic JCM800 setup is..." instead of "according to the JCM800 manual...". | (1) System prompt with explicit refusal rule + worked refusal example. (2) Force `[S{n}]` citation format; post-generation validation parses every marker and checks the cited chunk actually contains the adjacent claim. (3) Empty-context probe as a smoke test on day one. (4) Wrong-context probe (feed Marshall chunks, ask about Fender — must refuse). (5) Temperature 0.0–0.2. (6) UI shows chunk text alongside citation so user can spot-check. |
| **Semantic search fails on gear shortforms and numeric settings.** Dense retrieval is famously weak for short, exact, lexical queries: `TS9`, `JCM800`, `EVH`, `BD-2`, `Bass 5 Mid 7 Treble 8`. The two-mode structure of this domain (subjective prose + objective numerics) makes pure dense retrieval insufficient. | Queries with model numbers return generic/unrelated chunks; `grep -i 'BD-2' chunks` finds obviously relevant chunks that vector search missed; same query in formal language vs slang returns very different top-K. | (1) Track as a known limitation in Phase 1; the forum-only corpus mitigates somewhat (model numbers appear in prose context). (2) Build a `gear_aliases.json` file early (`TS9 <-> Ibanez Tube Screamer`, `Strat <-> Stratocaster`, `EHX <-> Electro-Harmonix`) and do bidirectional query expansion before embedding. (3) Append a normalized vocabulary line as chunk metadata. (4) Plan Phase 2 to add `tsvector` FTS + Reciprocal Rank Fusion. **The `pg_trgm` extension is installed in Phase 1 specifically to make this a config change later, not a migration.** |
| **pgvector setup gotchas silently degrade retrieval.** `CREATE EXTENSION vector` forgotten / partial migration; querying with the wrong distance operator falls back to seq scan with no error; IVFFlat built on empty table produces a useless index; unit-normalization assumption wrong for some embedding providers. | Suspiciously slow retrieval on a tiny corpus; `EXPLAIN ANALYZE` shows `Seq Scan on chunks`; bizarre similarity scores; top-K shifts wildly between identical queries. | (1) Migration script asserts `SELECT * FROM pg_extension WHERE extname='vector'` returned a row before proceeding. (2) Use HNSW (not IVFFlat) — works on empty table, no `lists` tuning, better recall defaults. (3) Standardize on cosine `<=>` everywhere; HNSW index built with `vector_cosine_ops`. (4) Verify OpenAI vectors are unit-norm with `np.linalg.norm(v)` on a sample at ingest time. (5) Add `EXPLAIN ANALYZE` to retrieval logging during Phase 1 development. (6) `ANALYZE chunks` after bulk ingest. |

## Critical Pitfalls

The top 5 pitfalls every phase planner must address.

### 1. Model fabricates gear advice from training knowledge instead of corpus
The project's value collapses silently if this isn't caught. Claude has strong baked-in opinions about Marshalls and Stratocasters. Defense in depth: rigid system prompt with refusal example; mandatory `[S{n}]` citations; post-gen validation that cited chunks actually contain the claim; empty-context and wrong-context smoke tests run before merging any prompt change; low temperature (0.0–0.2). The UI mitigation — showing chunk text adjacent to its citation — is the cheapest single fix and eliminates this entire failure class for a careful user.

### 2. Embedding model swap leaves stale or mixed-dimension vectors
`vector(N)` columns are typed; mixed-model vectors at the same dimension are *semantic nonsense* even when the math succeeds. Declare dimension explicitly. Add `embedding_model` and `embedded_at` columns. On API startup, assert the configured `EMBEDDING_MODEL` matches distinct values in the table or refuse to start. Re-ingestion always TRUNCATEs across model boundaries; never appends. Consider one table per model for clean A/B testing in Phase 3.

### 3. Query/document asymmetry — wrong embedding mode at query time
Voyage AI requires `input_type="document"` at ingest, `input_type="query"` at retrieval — using the wrong mode silently degrades quality with no error. OpenAI has no asymmetry, which makes it the easy default and the trap when swapping. The `Embedder` Protocol's two-method split (`embed_documents` vs `embed_query`) is the mitigation: provider-specific quirks encoded in one place, the protocol forces the caller to pick the mode. **Keep both methods even for OpenAI** so the call site is provider-agnostic.

### 4. Semantic search fails on exact gear specs and short numeric queries
Documented above as a Phase 1 risk. Phase 1 lives with it (forum-only corpus mitigates somewhat); Phase 2 must add `tsvector` hybrid retrieval with RRF. The `pg_trgm` and FTS infrastructure should be installed in Phase 1 to make this a config change, not a migration. The gear-alias map (`gear_aliases.json`) starts as soon as Phase 1 reveals the first lexical-mismatch failures.

### 5. PDF extraction garbles spec tables and signal-chain diagrams
Affects Phase 2 directly; threatens the most information-dense source in the corpus. Two-column layouts get merged row-wise; spec tables collapse into unstructured text; page headers/footers embed mid-sentence; vintage scanned manuals return empty text. Mitigation: `pypdf` for the boring 80%, escalate to `pymupdf4llm.to_markdown()` for table-heavy manuals (preserves table structure as Markdown), `ocrmypdf` CLI for scanned manuals (rare). Per-PDF validation: log char count and char-per-page ratio; flag manuals with <500 chars/page for review. **Never split inside a table during chunking** — keep the whole table in one chunk even if it exceeds 800 tokens.

### Honorable mentions (read PITFALLS.md for full list)

- **Chunks split across critical context boundaries** — naive fixed-size chunking splits knob-setting lists in half. Use structural chunking (headings, paragraphs, posts). Prepend `[Document Title > Section]` to every chunk's text for both embedding model and LLM context.
- **YouTube auto-captions mis-transcribe gear names** ("Tube Screamer" -> "chew scraper"). Prefer manually-authored captions; run post-extraction gear-name correction against the alias map; tag chunks with `transcript_quality: manual|auto` so retrieval can de-weight low-quality ones.
- **No golden eval set means optimization is vibes-based.** Build 20–30 (query, expected-chunk-ids, expected-themes) tuples at the end of Phase 1, before any retrieval tuning. Score with recall@K and MRR. This is the single highest-leverage process pitfall.

## Open Questions

These are unresolved and should be addressed during the relevant phase plan.

**Phase 1 plan must address:**
- Concrete schema for `documents`, `chunks`, `ingest_runs` tables — confirm exact column types match the patterns in STACK.md and ARCHITECTURE.md.
- Exact chunking parameters for forum posts (target tokens, overlap, post-delimiter detection on the actual `raw_data/forum_posts/*.txt` files). Inspect the actual files before locking numbers.
- Anthropic SDK streaming surface — verify `messages.stream(...).text_stream` against `anthropic==0.102.0` docs before coding (flagged MEDIUM confidence in STACK.md).
- Build the 20–30 query golden eval set against the 10 forum-post topics; reserve a held-out subset written *before* tuning begins to avoid biasing toward queries the developer already tried.
- Decide UI mechanism for `session_id` persistence (localStorage) and behavior when an old `session_id` references a session lost on server restart (must fall back to creating new, not 500).

**Phase 2 plan must address:**
- PDF parser escalation criteria (when does `pypdf` fail loudly enough to trigger `pymupdf4llm` reprocessing?).
- Per-manual smoke test process — 15 manuals x manual review of one chunk per manual is feasible and prevents silent garbage.
- Article scraping politeness (rate limit, caching to `raw_data/web_html/`), and the validation step that catches paywall snippets and Cloudflare challenges.
- YouTube transcript quality assessment for the 13 video IDs — which have manual captions vs auto-generated; per-video spot check of one chunk; populate `gear_aliases.json` with mis-transcription mappings as failures are observed.
- Source-type retrieval weighting ratios (start with 4 manual / 4 forum / 2 article / 2 youtube, tune empirically).

**Phase 3 plan must address:**
- Exact `tsvector` indexing strategy and RRF fusion implementation; confirm whether `pg_search`/`paradedb` is needed or if built-in FTS is sufficient.
- Voyage AI integration — confirm current `input_type` parameter against `docs.voyageai.com` at build time; one-table-per-model vs single-table-with-truncate for A/B.
- Multi-query rewriting implementation (Haiku-based) and the opt-in flag plumbing already present in the retrieval module from Phase 1.
- Post-generation gear-name validation regex strategy as a Phase 3 hardening step.

**Library-version checks to verify at implementation time:**
- `anthropic==0.102.0` streaming API surface (`messages.stream().text_stream`).
- `sentence-transformers==5.5.0` import/API surface vs the well-known v2.x patterns.
- Voyage AI `input_type` parameter naming and behavior.
- OpenAI `text-embedding-3-*` unit-norm guarantee (sample with `np.linalg.norm`).

---
*Synthesized: 2026-05-13*
