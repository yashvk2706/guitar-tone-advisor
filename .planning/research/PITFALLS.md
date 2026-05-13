# Pitfalls Research: Guitar Tone Advisor RAG

**Domain:** Personal guitar tone advisor, Python RAG from scratch, pgvector backend
**Researched:** 2026-05-13
**Confidence:** MEDIUM-HIGH overall. RAG mechanics (chunking, embeddings, pgvector behavior, prompting) draw from well-established practice — HIGH confidence. Guitar-domain failure modes (gear name mis-transcription, abbreviation matching, manual layout) are reasoned from corpus characteristics described in `PROJECT.md` plus general RAG patterns — MEDIUM confidence; recommend a small golden-set probe in Phase 1 to validate before scaling.
**Note on sources:** WebSearch / WebFetch / Context7 CLI were unavailable in this environment, so this synthesis relies on training-data knowledge of the pgvector docs, OpenAI/Voyage embedding documentation, and well-known RAG community pitfalls. Items requiring official-doc verification at implementation time are flagged with `[VERIFY]`.

---

## Critical Pitfalls (must address before shipping)

### 1. Model fabricates gear advice from training knowledge instead of corpus

**Risk:** Claude has strong opinions about a Marshall JCM800 baked into pretraining. If the retrieved chunks are weak, irrelevant, or empty, the model will quietly fall back on training knowledge and produce plausible-sounding settings that are *not* in the corpus. The user has no way to tell the difference, and the citations may even be invented or attached to chunks that don't actually contain those numbers. This is the single highest-stakes failure for this project — the entire value proposition ("grounded, citation-backed recommendations") collapses silently.

**Warning sign:**
- Answers contain specific knob values (e.g., "Treble 7, Mid 5, Bass 4") but the cited chunk doesn't contain those exact numbers.
- Answers mention gear that is not in any chunk's source (e.g., a pedal not present in `manuals/`).
- Answers look identical whether you pass real retrieved context or empty context — a quick A/B test exposes this fast.
- The model uses confident, general-purpose phrasing like "a classic JCM800 setup is..." rather than chunk-anchored phrasing ("according to the JCM800 manual section on...").

**Prevention:**
- System prompt: explicit "answer ONLY from the passages below; if the passages do not contain the answer, say `I don't have that in my corpus` and stop." Include a worked example of refusal in the prompt.
- Force citation format: every concrete setting must be followed by `[chunk_id]`, and the post-generation layer validates that the cited chunk actually contains the claim (numeric / substring check on the knob value).
- Run an empty-context probe as a smoke test: pass `retrieved_chunks=[]` and verify the model refuses rather than answers.
- Run a wrong-context probe: feed it Marshall chunks and ask about a Fender Twin — model should refuse rather than confabulate.
- Lower temperature for the generation call (0.0–0.2). High temperature makes the fallback-to-training-knowledge failure more common.

**Phase:** Generation / chat phase. Most at risk in Phase 1 MVP when the corpus is small (only 10 forum posts) — many queries will land on weak retrievals and the model will be tempted to fill the gap.

---

### 2. Embedding model swap leaves stale vectors in the table (dimension mismatch silent failure)

**Risk:** The project explicitly aims to swap `EMBEDDING_MODEL` between `text-embedding-3-small` (1536-d), `text-embedding-3-large` (3072-d), and Voyage models (1024-d or 1536-d depending on model). pgvector columns are typed `vector(N)` — a hard dimension. Three failure modes here:
1. Column declared `vector(1536)` → swap to `text-embedding-3-large` → INSERT fails loudly (good — easy fix).
2. Column declared generic `vector` (no dim) → INSERTs succeed at multiple dimensions → similarity queries return garbage because you're comparing vectors of different lengths, or pgvector errors out cryptically. [VERIFY: pgvector now rejects mixed-dim comparisons, but generic-column allows mixed insert.]
3. Worst case: you change models, re-run ingestion on a subset, and now the table contains a *mix* of `text-embedding-3-small` vectors and `voyage-3` vectors at the same dimension (both happen to be 1536). Queries return technically-valid neighbors but the similarity scores are semantic nonsense — the spaces are not comparable. **This fails silently.**

**Warning sign:**
- Suddenly poor retrieval after a model change with no other code change.
- Mixed timestamps or `embedding_model` values in the chunks table (if you have that column).
- Top-K results that "look fine" but include obvious irrelevant chunks alongside obvious matches.

**Prevention:**
- Schema: declare `vector(N)` explicitly with the exact dimension of the chosen model.
- Add a `embedding_model` text column and a `embedded_at` timestamp column on every chunk row.
- On startup, the retrieval layer asserts that the configured `EMBEDDING_MODEL` matches the distinct `embedding_model` values in the table — if not, refuse to start and tell the user to re-ingest.
- Re-ingestion script always TRUNCATEs (or uses a separate table per model) — never appends across models.
- Consider one table per model (`chunks_openai_small`, `chunks_voyage_3`) for clean A/B testing without risk of cross-contamination.

**Phase:** Embedding/ingestion phase. The pitfall *manifests* in retrieval, which is what makes it dangerous. Most at risk during Phase 2+ when comparing embedding models.

---

### 3. Query/document asymmetry — wrong embedding mode at query time

**Risk:** Several embedding providers require different "input types" or prefixes for documents vs queries:
- **Voyage AI:** explicit `input_type="document"` at ingestion and `input_type="query"` at query time. Using the same mode for both *measurably* degrades retrieval. [VERIFY against current Voyage docs at implementation.]
- **Some open-source models** (e.g., E5, BGE) require literal text prefixes like `"query: "` and `"passage: "`.
- **OpenAI `text-embedding-3-*`:** no asymmetry — same call for both. (This makes it the safe default but also the trap when you swap to Voyage and forget.)

If you wrote a generic `embed(text)` helper that doesn't accept an input-type argument, you will use the same mode for both and silently lose retrieval quality. There is no error — just worse top-K rankings.

**Warning sign:**
- Retrieval quality drops noticeably after swapping to a model with asymmetric encoding.
- The same query against the same corpus returns markedly different top-K orderings vs the documented benchmarks of the embedding model.

**Prevention:**
- The embedding wrapper takes a mandatory `mode: Literal["document", "query"]` argument. No default.
- Per-provider adapter encodes the model's quirks (prefix string, `input_type` parameter) in one place.
- Document this in code comments and in `STACK.md` so it's not lost on the next model swap.
- Include in the golden eval set a check that retrieval quality is within expected bounds for each supported model.

**Phase:** Embedding phase (ingestion + query layer). At risk every time a new model is added.

---

### 4. Semantic search fails on exact gear specs and short numeric queries

**Risk:** Dense retrieval is famously weak for short, exact, lexical queries:
- "TS9 settings" — three tokens, the abbreviation may not match well against manual prose that says "Ibanez Tube Screamer TS9".
- "set Treble to 7" — almost entirely stop-words plus a number; cosine similarity treats this as low-information.
- "JCM800 model 2203" — model numbers are essentially out-of-vocabulary tokens for some embedding models.
- "EVH 5150" — embedding model may not know this refers to Eddie Van Halen's amp.

The corpus contains both prose ("the bright channel has a glassy character") and numeric specifications ("EQ: Bass 5, Mid 6, Treble 8, Presence 3"). Dense embeddings are good at prose, bad at the numbers — which is the most actionable part of the answer for this user.

**Warning sign:**
- Queries containing model numbers or abbreviations return generic/related chunks instead of the specific gear's manual.
- The user asks "what should I set the Boss DS-1 distortion knob to?" and the top result is a forum post about a different distortion pedal entirely.
- A keyword search by hand (`grep -i 'DS-1' chunks`) finds obviously relevant chunks that dense retrieval missed.

**Prevention:**
- **Hybrid retrieval from day one.** Combine dense (pgvector cosine) with sparse (Postgres full-text search, `tsvector`, or BM25 via `pg_search` / `paradedb` [VERIFY: extension name and availability]). At minimum, add a `to_tsvector` column on each chunk and run an OR query: dense top-K + FTS top-K, then merge and re-rank.
- Build a small gear-name synonym/alias map: `{"TS9": "Ibanez Tube Screamer TS9", "JCM": "Marshall JCM800", "EVH": "Eddie Van Halen 5150", "Big Muff": "Electro-Harmonix Big Muff Pi", ...}`. Expand the query before embedding *and* keep the original for FTS.
- Index chunk metadata (gear name, manufacturer, model number) as structured fields and allow filtered retrieval: "WHERE gear_name = 'DS-1' ORDER BY embedding <=> :q LIMIT 5".
- Reciprocal Rank Fusion (RRF) is a simple, robust way to merge dense + sparse rankings — implement it once, reuse for every query.

**Phase:** Retrieval phase. This is the pitfall most likely to make the MVP feel broken on launch. Must be addressed in Phase 1 if any real queries are going to mention model numbers or settings.

---

### 5. PDF manual extraction garbles spec tables and signal-chain diagrams

**Risk:** The 15 amp/pedal manuals are the **most information-dense** source — they contain the exact settings and parameter ranges that are the project's core value. But PDF extraction is notoriously hostile:
- Two-column layouts get merged row-wise (`"Bass Treble"` becomes a single text run instead of two column headers).
- Spec tables become unstructured text: `"Knob | Range | Default | Bass | 0-10 | 5"` collapses into `"Knob Range Default Bass 0-10 5"`.
- Page headers/footers ("Marshall JCM800 Owner's Manual — page 4") get embedded mid-sentence in chunks.
- Vintage manuals (Marshall JTM45, Vox AC30 reissues) often contain **scanned images** rather than text layer — `PyPDF2`/`pdfplumber` return empty strings; OCR is required.
- Knob diagrams and signal-chain illustrations are image-only and contain crucial info ("input → compressor → drive → modulation → delay → reverb → amp") that text extraction misses entirely.

If chunks are silently empty or jumbled, the rest of the pipeline still "works" — embeddings get generated for the garbage text, retrieval returns garbage chunks, the LLM tries to answer from them, and the citation looks legitimate.

**Warning sign:**
- Chunk character counts have a long tail of suspiciously short chunks (<100 chars) — likely OCR-empty pages.
- Random sample of 10 chunks per manual shows: header/footer text interleaved with body, missing columns from spec tables, or pure whitespace.
- Asking "what is the bass control range on the Mesa Mark V?" returns chunks that don't contain the number.
- Total character count of extracted text from a manual is dramatically less than expected (a 40-page manual yielding 2KB of text = it's scanned).

**Prevention:**
- Per-PDF extraction validation step: log character count, page count, ratio. Flag any manual with <500 chars/page for manual review.
- Use a layout-aware extractor: `pdfplumber` for text+tables, fall back to `pymupdf` (fitz) for tricky layouts, fall back to `ocrmypdf` or `tesseract` for scanned pages. [VERIFY current best-in-class — landscape changes yearly.]
- Strip headers/footers using positional heuristics (top/bottom 10% of page, repeated text across pages) before chunking.
- Preserve table structure: extract tables separately with `pdfplumber.extract_tables()` and serialize them as Markdown tables in the chunk text (LLMs read Markdown tables well). Do not let tables flatten into prose.
- Manual smoke test per manual: open the chunked output for one page, eyeball that the spec table is intact and the signal-chain advice is readable. This is a 30-minute task during Phase 2 ingestion and saves hours of mystery later.
- For scanned-only manuals, decide explicitly: OCR with quality checks, or exclude with a note in the corpus inventory.

**Phase:** Ingestion phase (PDF parser). Effects propagate to every downstream phase.

---

### 6. Chunks split across critical context boundaries

**Risk:** Naive fixed-size chunking (e.g., 500 tokens with 50 overlap) will routinely:
- Split a knob-setting list in half: chunk A ends with "Bass: 5, Mid:" and chunk B starts with "7, Treble: 8". Retrieval may return only one half. The model now sees "Bass: 5, Mid:" with no continuation and either refuses or hallucinates.
- Split a spec table from its header: chunk B contains `"5 | 7 | 8 | 3"` with no column labels — semantically useless.
- Split an artist-tone forum post from its punchline ("...so the secret is to roll the tone knob back to 3, not 7 as most people think").

**Warning sign:**
- Top-K chunks contain partial sentences ending or starting mid-clause.
- Numeric lists or bullet lists appear split across chunks.
- A retrieved chunk references "the table above" or "as shown" — the antecedent is in the prior chunk.

**Prevention:**
- Use **structural chunking, not fixed-size**:
  - Forum posts: chunk by post or by Q-A pair, not by length.
  - PDF manuals: chunk by section heading where detectable, and *never* split inside a recognized table.
  - YouTube transcripts: chunk by sentence-boundary windows (e.g., 30-second segments aligned to punctuation).
  - Articles: chunk by paragraph or H2/H3 boundary.
- Always include the section heading and document title as a prepended metadata line in each chunk text — gives both the embedding model and the LLM the context: `[Marshall JCM800 Manual > EQ Section] Bass: 5, Mid: 7...`
- Use sentence-aware splitting (e.g., `nltk.sent_tokenize` or `pysbd`) as a last resort for length overflow — never split mid-sentence.
- Aim for 200–500 tokens per chunk for this corpus (small enough to be focused, large enough to contain a full setting block). Larger chunks dilute embeddings; smaller chunks lose context.
- Include 1–2 sentence overlap between adjacent chunks for prose continuity, but disable overlap inside tables.

**Phase:** Ingestion / chunking phase. Effects show up at retrieval and generation.

---

## Important Pitfalls (address during relevant phase)

### 7. YouTube auto-caption noise mis-transcribes gear names

**Risk:** YouTube auto-generated captions for guitar content are unreliable. Known failure patterns observed across the gear-content ecosystem:
- "Tube Screamer" → "chew scraper" / "two screamer"
- "Stratocaster" → "Stratocastor" / "stratocast or"
- "Big Muff" → "big mouth" / "big mop"
- "Klon Centaur" → "clone centaur" / "clown center"
- Punctuation entirely missing → 30-minute single sentence → chunking by sentence boundary fails.
- Speaker change not marked → host's question fuses with guest's answer.

If "Tube Screamer" is mis-transcribed throughout a video, the embedding for that chunk no longer matches a "Tube Screamer" query — and FTS won't save you either because the literal string is wrong.

**Warning sign:**
- A video known to discuss a specific pedal returns no hits when queried by that pedal name.
- Random sampling of YouTube chunks shows obviously broken gear names.
- Chunk character count vs duration is unusually low (compressed/repeated text suggests captions failed).

**Prevention:**
- Prefer videos with **manually-authored captions** (the YouTube transcript API exposes which is which) — drop or de-weight auto-generated ones.
- Run a post-extraction normalization pass: gear-name spell-correction against the known-gear vocabulary (the same alias map from pitfall #4). E.g., regex-replace `"chew scraper"` → `"Tube Screamer"`.
- For the 13 videos in the corpus, manually spot-check one chunk per video — this is 13 quick reviews, not a scaling problem.
- Tag each chunk's metadata with `transcript_quality: manual|auto` so retrieval can de-weight low-quality sources when ranking is close.

**Phase:** Ingestion phase (YouTube parser).

---

### 8. Top-K too small misses relevant chunks; too large dilutes context

**Risk:** A tone question may legitimately need 5–10 chunks: one for the amp, one for the drive pedal, one for the artist's known settings, one for the signal-chain ordering advice. If `top_k=3`, you'll miss half. If `top_k=20`, the prompt fills with weakly-related material and the LLM either gets confused or the most-relevant chunk (which may be ranked #1) gets attention-diluted by the noise.

**Warning sign:**
- Answers consistently mention only the amp or only the pedal, never both, when a query asks about a signal chain.
- Adding more retrieved chunks (raising top_k) actually makes answers worse rather than better.
- The LLM cites only 1–2 chunks even when many are passed in.

**Prevention:**
- Start at `top_k=8` for this corpus size. Tune empirically with the golden eval set.
- Implement a similarity-score cutoff (e.g., drop any chunk with cosine similarity < 0.3) — this keeps top-K adaptive: easy queries pull 3 chunks, hard queries pull 8.
- Use a small re-ranker step (even a cheap one: ask Claude Haiku "rank these 20 chunks by relevance to the query") to compress 20 → 6 before the final generation. [VERIFY: cost/latency acceptable for personal-use single-user app.]
- Log the chunk count actually used per query — it tells you whether retrieval is over- or under-feeding the generator.

**Phase:** Retrieval phase. Tune in Phase 1 once the golden eval set exists.

---

### 9. Citation hallucination — model claims a chunk says something it doesn't

**Risk:** Even with a strict system prompt, the model will occasionally cite chunk `[3]` while stating a number that isn't in chunk `[3]`. The citation gives the answer a veneer of grounding while the content is fabricated. Worse, the user trusts cited answers *more*, so this is high-confidence wrong information.

**Warning sign:**
- Spot-checking a cited setting against the source chunk fails — the number isn't there, or a different number is.
- Citations are inconsistent: same query asked twice cites different chunks.
- The model cites every chunk in the context window even when only 1–2 are relevant (it's pattern-matching the citation format without grounding).

**Prevention:**
- Post-generation citation validation: parse each `[chunk_id]` and verify that the claim adjacent to it has a substring/numeric match in chunk_id's text. If not, either strip the citation, flag the claim, or re-prompt with "your citation does not match — please fix or remove the claim."
- Prompt with a worked example showing correct citation behavior AND an example of a refusal when the chunk doesn't contain the claim.
- Display each chunk's text alongside the answer in the UI — the user can spot-check directly. (Trivial for single-user UX, eliminates this whole class of failure for the careful user.)
- Log every answer with its cited chunk IDs and the user's query for spot auditing during MVP.

**Phase:** Generation phase + UI phase (the UI mitigation is the cheapest fix).

---

### 10. Conversation history evicts retrieved chunks from context window

**Risk:** Multi-turn chat means the prompt grows. By turn 5 the conversation history could be 4000 tokens, retrieved chunks could be 4000 tokens, system prompt 500 tokens — Claude's context is fine, but **what gets dropped first is often the earliest retrieved chunks** if you're concatenating naively, or the model's *attention* shifts toward the recent history and the chunks get neglected. Either way, grounding degrades over a long session.

**Warning sign:**
- Answers in turn 1 are well-grounded; by turn 5 they drift toward general gear knowledge.
- Late-turn answers reference settings from earlier turns without re-citing the source.
- Total prompt token count climbs steadily across a session.

**Prevention:**
- Re-run retrieval **on every turn** with the latest user message (optionally with conversation context as a query-rewrite input — "rewrite this into a standalone retrieval query").
- Don't accumulate retrieved chunks across turns — each turn gets its own fresh top-K, no carryover.
- Cap conversation history to last N turns (e.g., 6) or summarize older turns into a single message.
- Place retrieved chunks **closer to the end of the prompt** than the conversation history — LLMs attend more strongly to the end of long contexts. [VERIFY: "lost in the middle" research applies to Claude — generally yes but model-version dependent.]
- Tell the model in the system prompt: "Each turn comes with a fresh set of retrieved passages. Do not rely on passages from previous turns — they are not in this prompt."

**Phase:** Generation phase + chat orchestration.

---

### 11. pgvector index misconfiguration silently degrades or skips retrieval

**Risk:** Several pgvector gotchas can degrade retrieval without errors:
- **`CREATE EXTENSION vector` forgotten** — first INSERT fails with "type vector does not exist". Easy to fix, but if the migration runs partially you get half a schema.
- **IVFFlat needs `ANALYZE` after data load** for the planner to pick the index. If you skip it, queries silently do sequential scans — correct results but slow. [VERIFY: applies primarily to IVFFlat; HNSW behavior differs.]
- **IVFFlat `lists` parameter** — rule of thumb is `lists = rows / 1000` for <1M rows and `sqrt(rows)` for >1M. Setting it too high on a small corpus (this project will have maybe 2K–10K chunks) means most lists are nearly empty and recall drops sharply.
- **HNSW build time** scales with corpus size — fine for 10K chunks, painful at 1M. Not a v1 issue for this project but a future trap.
- **Distance operator mismatch**: pgvector has `<->` (L2), `<=>` (cosine), `<#>` (inner product). The index is built for ONE of these — querying with the wrong operator still works but doesn't use the index, falling back to a seq scan. Silently slow.
- **Not normalizing vectors for inner-product**: cosine similarity via `<=>` handles normalization internally; using `<#>` requires pre-normalized vectors, otherwise the "similarity" is dominated by magnitude. OpenAI returns unit-norm vectors by default; Voyage's behavior varies by model. [VERIFY.]

**Warning sign:**
- Retrieval is suspiciously slow even on a small corpus (sequential scan instead of index).
- `EXPLAIN ANALYZE` on the retrieval query shows `Seq Scan on chunks` instead of an index scan.
- Similarity scores look bizarrely large or small (sign of magnitude pollution from un-normalized inner-product).
- Top-K results change wildly between query runs (sign of IVFFlat with too few `probes`).

**Prevention:**
- Migration script checks `CREATE EXTENSION IF NOT EXISTS vector` as step 1, and validates with `SELECT * FROM pg_extension WHERE extname='vector'` before proceeding.
- After bulk ingest, explicitly run `ANALYZE chunks` (or whatever the table is named).
- For this corpus size, use **HNSW** rather than IVFFlat — HNSW has better recall out of the box, doesn't need `lists` tuning, and the build cost is negligible at <10K chunks. [VERIFY current pgvector HNSW defaults.]
- Standardize on cosine distance (`<=>`) and ensure embeddings are unit-normalized at ingest (most providers do this, but verify with `np.linalg.norm(v)` on a sample).
- Add an `EXPLAIN ANALYZE` line to the retrieval logging during development so you see the plan on every query.

**Phase:** Database / retrieval phase. Most at risk during initial schema setup and any time the corpus grows by 10x.

---

### 12. Forum colloquialisms and abbreviations bypass semantic search

**Risk:** Closely related to pitfall #4 but specific to the forum corpus. Forum posts use:
- Slang: "trans-parent OD" instead of "transparent overdrive"; "broken-up" to mean "lightly distorted clean amp"; "amp-in-a-box" for a particular type of preamp pedal.
- Brand abbreviations: "EHX" for Electro-Harmonix, "MIJ" for Made-In-Japan, "BJF" for the boutique pedal builder.
- Model shorthand: "Strat", "Tele", "LP" (Les Paul), "335" (ES-335), "the Twin" (Fender Twin Reverb).
- Tone descriptors: "spank", "quack", "snap", "chime", "glassy", "scoop" — high-information words to a guitarist, ambiguous to an embedding model trained mostly on general web text.

The forum corpus is the *richest* source of opinionated, applied advice — and also the most vocabulary-mismatched with the manuals, which use formal names. A query against forum-style language may miss a manual that has the exact spec, and vice versa.

**Warning sign:**
- A forum query like "best Strat-and-Twin tone for funk" misses the Fender Twin Reverb manual entirely.
- The same query asked in formal language ("Fender Stratocaster with Fender Twin Reverb amp, funk genre") returns a different top-K.

**Prevention:**
- Maintain a domain vocabulary file (`gear_aliases.json`) with bidirectional mappings. Apply it as a **query rewriting** step before embedding: expand abbreviations both directions ("Strat" → "Stratocaster" AND keep "Strat"; "Marshall JCM800" → also embed as "JCM" for retrieval).
- During ingestion, append a normalized vocabulary line to each chunk: `[aliases: Strat=Stratocaster, Twin=Fender Twin Reverb]`. This gives the embedding model a chance to bridge the gap.
- Use FTS as a backstop — exact-string matching catches all the abbreviations that semantic search misses.
- This list grows; budget time in each phase to add to it as failures are observed.

**Phase:** Retrieval phase + ingestion phase (chunk metadata enrichment).

---

### 13. No golden eval set, so optimization is vibes-based

**Risk:** Without a fixed set of queries with known-good expected answers and known-good expected chunks, every retrieval/embedding/prompt change is judged subjectively. The result: you'll improve one query and regress another without noticing, and after 5 changes you'll have no idea whether the system is better or worse than where you started.

**Warning sign:**
- "It feels better now" is the only metric for whether a change worked.
- The same query gives different-quality answers on different days and there's no way to tell whether it's the system or the question's randomness.
- Changes get reverted because someone noticed *one* example got worse, with no way to weigh that against the unmeasured improvements.

**Prevention:**
- Before tuning retrieval at all, build a **golden set** of 20–30 (query, expected-chunk-ids, expected-answer-themes) tuples. For this project, derive them from the 10 forum-post topics in the corpus — each topic naturally yields 2–3 evaluable queries.
- Score retrieval on **recall@k** (did the expected chunk appear in top-K) and **MRR** (mean reciprocal rank).
- Score answers on **citation accuracy** (did the cited chunk actually contain the claim) and **claim coverage** (did the answer cover the expected themes) — both can be partially LLM-judged with Claude Sonnet as a grader, with periodic human spot checks.
- Re-run the eval set as a CI-like step before any merge that touches retrieval, embeddings, chunking, or prompts.
- Track the eval results in a simple CSV over time — you want a trend line, not snapshots.

**Phase:** Evaluation phase, which should start at the end of Phase 1 — *before* most tuning work begins. This is the single highest-leverage process pitfall.

---

### 14. Premier Guitar article scraping breaks or violates ToS

**Risk:** The `article_urls.txt` corpus relies on web scraping. Common pitfalls:
- Anti-scraping (rate limiting, JS rendering required, Cloudflare challenge) — `requests.get()` returns a challenge page instead of content. Silent failure.
- Article body extraction picks up the boilerplate (nav, comments, "related articles") instead of the article text — chunks get polluted with site chrome.
- Paywall snippets only — first paragraph extracted, rest paywalled, chunks are misleadingly short.
- Robots.txt or ToS violation — risk for the user, especially if this project ever gets shared.

**Warning sign:**
- Article chunks contain navigation strings ("Subscribe to our newsletter", "Read more articles", "© 2025").
- Article character counts are dramatically shorter than expected for a multi-page article.
- Scraping silently returns a 200 status with a "checking your browser..." page.

**Prevention:**
- Use a library like `trafilatura` or `newspaper3k` for boilerplate-aware extraction rather than raw `BeautifulSoup` — they're specifically built for article-body extraction. [VERIFY current recommendation.]
- Validate after scraping: minimum char count, presence of expected markers (article title, byline). Failed scrapes go to a manual-review queue, not to ingestion.
- Respect robots.txt and add a polite rate-limit (1 req / 3s) and a real User-Agent.
- For paywalled content, accept manual export (save-as HTML in browser, then ingest from disk) — for a 10-URL personal corpus this is feasible.
- Cache raw scraped HTML on disk so a re-ingest doesn't re-hit the site.

**Phase:** Ingestion phase (web scraper).

---

## Known Failure Modes in This Domain

### Semantic similarity vs exact-spec retrieval mismatch

Guitar tone knowledge has a **two-mode structure**:
- **Subjective/prose mode**: "warm", "punchy", "scooped", "spongy" — these are perfect for dense retrieval. Embedding models capture timbral-descriptor similarity reasonably well.
- **Objective/numeric mode**: "Bass 5, Mid 7, Treble 8, Master 4, Presence 3" — embedding models treat numbers as low-information tokens. Cosine similarity over a knob-setting list is nearly meaningless.

The user's queries will mix both modes ("I want a warm, smooth blues lead tone — what settings on my JCM800?"). Pure dense retrieval handles the first half well and the second half poorly. **The reverse is also true**: pure FTS handles "JCM800" perfectly and "warm smooth blues" weakly. Hybrid retrieval is not a nice-to-have for this domain — it is the only correct approach.

### Gear-name ambiguity and disambiguation

- "Tube Screamer" refers to a *family* of pedals (TS9, TS808, TS10, TS-Mini, etc.) with audibly different circuits. A naive chunk match on "Tube Screamer" may return a TS10 manual when the user has a TS9.
- "Marshall" is a brand spanning JCM800, JCM900, JTM45, Plexi, DSL, JVM — vastly different amps. Retrieval must distinguish or the answer will conflate them.
- "Big Muff" has had at least a dozen revisions over decades (Triangle, Ramshead, Civil War, Op-Amp, Sovtek, NYC reissue, Russian, Nano, Deluxe), each tonally distinct.

Mitigation: encode the **specific model** in chunk metadata at ingest. When the user asks about "Tube Screamer", clarify in the response which variant the cited chunk covers ("according to the TS9 manual...").

### Signal-chain order is sequential and easily lost

Pedal order matters acoustically: drive → modulation → delay → reverb sounds different from delay → drive. A chunk that says "put the drive *before* the modulation" loses meaning if "before" is dropped during chunking or if the chunk is retrieved without its context. Similarly, a manual that describes the amp's effects loop position is meaningless if just the FX-loop section is retrieved without the surrounding "this is what goes into the loop vs in front of the amp" prose.

Mitigation: in PDF manual chunking, never split inside a "Signal Chain" or "Setup" section. In forum chunking, prefer whole-post chunks for signal-chain advice. Include section context as chunk prefix.

### Artist-tone forum posts mix anecdote with actionable advice

A forum post about EVH's "brown sound" often contains 80% anecdote ("I saw him in '84 and he was using...") and 20% actionable settings ("a Variac at 90V, 5150 head, Treble 8, Mid 7, Bass 5"). Naive chunking can return the anecdote and lose the settings, or return the settings stripped of context (which 5150 revision?).

Mitigation: structure-aware chunking for forum posts (Q-A pair as a unit, or whole post as a unit if under length limit). Include post title and original-poster question as chunk prefix.

---

## Evaluation Anti-Patterns

### Anti-pattern 1: Vibes-checking instead of measuring
Asking the system one question, eyeballing the answer, declaring it "good" or "bad". Sample size of one. **Do this for sanity checks during development; never use it to justify a change.**

### Anti-pattern 2: Measuring retrieval recall only, not end-to-end answer quality
Retrieval recall@5 of 100% is meaningless if the LLM ignores the retrieved chunks or hallucinates citations. Always evaluate at the **answer level**, not just the chunk level. Retrieval metrics are diagnostic, not the goal.

### Anti-pattern 3: Evaluating against the same queries that informed the design
Building the golden eval set from queries you already tried during development biases everything toward those queries. Reserve a held-out set written *before* the system works, ideally by a different author or by asking the user for queries they'd actually want to ask.

### Anti-pattern 4: Using only one embedding model to score retrieval
If you score retrieval quality by comparing embeddings to the same model used at query time, you're testing whether the model is self-consistent, not whether it's correct. Use **rank-based** metrics (recall@k, MRR) tied to human-labeled ground truth, not embedding-based metrics like "average cosine similarity to expected chunk".

### Anti-pattern 5: Aggregate scores without per-query inspection
A mean MRR of 0.6 across 30 queries could mean "most queries score around 0.6" or "half score 1.0 and half score 0.2". The second case has actionable failure clusters; the first does not. Always inspect per-query scores and look for clusters of failures (e.g., all the queries about pedals score badly — implies a pedal-corpus problem).

### Anti-pattern 6: No regression suite between changes
Changing the chunker, the embedding model, the top-K, and the prompt in the same session without re-running the eval after each change. You'll never know which change caused which delta. Treat the eval set as the regression test, and gate one change at a time.

### Anti-pattern 7: Trusting LLM-as-judge without calibration
Using Claude Sonnet to grade Claude Sonnet's answers can give plausible-looking but uncorrelated-with-truth scores, especially on the citation-grounding axis (the judge tends to be lenient about claims that "sound right"). Spot-check 10% of the LLM-judge scores against a human review monthly; recalibrate the judging prompt if drift is observed.

---

## Phase Mapping Summary

| Phase | Highest-priority pitfalls to address |
|-------|--------------------------------------|
| **Phase 1: MVP (forum-only RAG slice)** | #1 model fabricates, #4 semantic-vs-exact, #6 chunk boundaries, #11 pgvector setup, #13 golden eval set |
| **Phase 2: Corpus expansion (manuals, articles, YouTube)** | #5 PDF extraction, #7 YouTube captions, #14 article scraping, #6 chunk boundaries (per-source) |
| **Phase 3: Embedding model swap / comparison** | #2 stale embeddings, #3 query/doc asymmetry, #11 pgvector index per dim |
| **Phase 4: Chat UX polish** | #9 citation hallucination, #10 conversation history |
| **Continuous** | #8 top-K tuning, #12 vocabulary expansion, #13 eval set maintenance |

---

## Open questions for implementation-time verification

- `[VERIFY]` pgvector current HNSW defaults and whether IVFFlat is still recommended for any corpus size now that HNSW is GA.
- `[VERIFY]` Voyage AI current `input_type` parameter for query vs document — confirm against `docs.voyageai.com` at build time.
- `[VERIFY]` Best Python PDF extraction library for layout+tables in 2026 — `pdfplumber`, `pymupdf`, `unstructured`, or newer alternatives.
- `[VERIFY]` Postgres FTS vs `pg_search`/`paradedb` for sparse retrieval — is `tsvector` good enough, or worth the extension?
- `[VERIFY]` Whether OpenAI `text-embedding-3-*` returns unit-normalized vectors by default (training-data says yes, but check sample with `np.linalg.norm`).
- `[VERIFY]` Trafilatura vs newspaper3k vs newer article-extraction libraries for Premier Guitar content specifically — sites change anti-scraping behavior.

---

*Researched: 2026-05-13*
