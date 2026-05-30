# Phase 6: Full Corpus Ingestion - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement the three `NotImplementedError` branches in `app/ingest/chunker.py::chunk_document()` — one each for `pdf_manual`, `web_article`, and `youtube_transcript` source types — and extend `app/ingest/pipeline.py` to load and ingest all four source types in a single `python -m app.ingest.pipeline` invocation. Then run the full pipeline against `raw_data/` and verify that eval scores (`recall@8 ≥ 1.0`, `MRR ≥ 0.9`, `faithfulness ≥ 0.5`) improve over the forum-only baseline.

**In scope:** `app/ingest/loader.py` additions (PDF, YouTube, article loaders); `app/ingest/chunker.py` additions (PDF, YouTube, article chunkers); `app/ingest/pipeline.py` orchestration of all 4 source types; `tests/` unit and integration tests for the new loaders/chunkers; running the full pipeline and verifying eval scores.

**Out of scope:** Hybrid retrieval (tsvector + RRF — RETR-05, v2), multi-query rewriting (RETR-06), Voyage AI embedder (RETR-07), any UI changes, authoring new golden eval tuples.

</domain>

<decisions>
## Implementation Decisions

### PDF Chunking Strategy
- **D-01:** Section-aware chunking using heading detection from `pymupdf4llm`'s markdown output. The markdown representation exposes `#`, `##` heading lines that delineate manual sections (Controls, Specifications, Troubleshooting, etc.). Each section boundary starts a new chunk group.
- **D-02:** Within each section, apply the same greedy 300–500 token paragraph-packing logic as the forum chunker (tiktoken `cl100k_base`, `MAX_TOKENS=500`). A section too large for one chunk (e.g., a 700-token Controls section) gets split into sub-chunks tagged with the same `section_heading`.
- **D-03:** PDF chunk metadata includes `section_heading` (detected heading text, or `""` for pre-heading content) and `page_number` (1-based). `source_filename` stays as in Phase 1.
- **D-04:** Skip first page unconditionally (cover art/title page). Skip any page where >50% of its text lines are short identifier-only content (ToC entries like `Chapter 1 … 3`). Prevents ToC/cover pollution in retrieval.

### pymupdf4llm vs pypdf
- **D-05:** Use `pymupdf4llm` as the **primary** extractor for all PDFs — its markdown output is required for heading detection (D-01). `pypdf` acts as a fallback: if `pymupdf4llm` raises an exception on a specific file, retry with `pypdf` plain-text extraction + paragraph-packing (section headings unavailable in that path; `section_heading=""` for all chunks). This preserves the CLAUDE.md constraint while keeping the happy path simple.
- **D-06:** Tables from `pymupdf4llm` are kept in GFM markdown table format (`| col | col |`) as-is. The CLAUDE.md hard constraint ("never split inside a table") is automatically honored because `pymupdf4llm` emits the complete table as a single markdown block — the chunker must not split that block.

### Failure Handling (all source types)
- **D-07:** Skip-and-log for all three new source types. On failure, log a `WARNING` with the resource identifier and reason, then continue to the next item. Run succeeds as long as at least one item per source type is processed.
  - **YouTube:** `youtube-transcript-api` primary, `yt-dlp` fallback. If both fail (private video, no captions, geo-blocked), log and skip. Print end-of-run summary: `"Transcripts: N of M videos ingested (K skipped)"`.
  - **Articles:** Run `trafilatura.fetch_url()` + `trafilatura.extract()`. If the extracted text is under 100 words (paywall boilerplate or empty), log and skip. End-of-run summary: `"Articles: N of M URLs ingested (K skipped)"`.
  - **PDFs:** If `pymupdf4llm` and `pypdf` fallback both raise, log and skip the file. End-of-run summary: `"PDFs: N of M files ingested (K skipped)"`.
- **D-08:** The pipeline does not fail the run when individual items are skipped. It only exits non-zero if an unrecoverable error occurs (DB connection failure, embedder error, etc.) — same as the existing forum pipeline behavior.

### YouTube Transcript Chunking
- **D-09:** Non-overlapping 300–500 token windows, same greedy-pack budget as the forum chunker. No sliding window overlap. The corpus is small enough that boundary misses won't meaningfully hurt `recall@8`.
- **D-10:** YouTube chunk metadata carries `video_id` (the raw 11-char ID from the file) and `start_time` (float, seconds from start of video for the first caption segment in the window). Enables the citation drawer to show `"YouTube, 2:34"` with a deeplink.
- **D-11:** Parse `raw_data/youtube_ids.txt` line by line: strip everything after `#` (inline comments), strip whitespace, skip blank lines. Lines like `sQU-gJ5Uyck # John mayer neural DSP plugin` → ID is `sQU-gJ5Uyck`.

### Article Chunking
- **Claude's Discretion:** Use the same greedy 300–500 token paragraph-packing logic as the forum chunker on trafilatura's extracted text. `source_filename` → article URL. No section-aware chunking needed (article structure is prose-dominant).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Ingest Infrastructure
- `app/ingest/chunker.py` — `chunk_document()` dispatch + `chunk_forum()` implementation; `Chunk` dataclass with `chunk_index`, `text`, `token_count`, `content_hash`, `metadata` fields; `MAX_TOKENS=500`, `MIN_PARAGRAPH_WORDS=40`, `_ENCODING`
- `app/ingest/loader.py` — `RawDocument` dataclass (`source_type`, `source_name`, `raw_text`, `metadata`); `load_forum_posts()` pattern to follow for new loaders
- `app/ingest/pipeline.py` — pipeline wiring, per-document `conn.commit()` pattern, `--full-rebuild` flag, `start_run`/`complete_run`/`fail_run` audit lifecycle
- `app/ingest/writer.py` — `upsert_document()`, `upsert_chunks()`, `chunks_to_embed()` — reused unchanged by all new source types

### Phase 1 Eval Infrastructure
- `eval/golden_set.jsonl` — 22 GoldenTuples; `held_out: true` on 5 entries — the primary scoring target
- `eval/HELD_OUT.md` — locked held-out split; the 5 held-out queries are the eval gate
- `app/eval/retrieval.py` — `python -m app.eval.retrieval` CLI; run after full ingest to verify `recall@8 ≥ 1.0` and `MRR ≥ 0.9`
- `app/eval/ragas.py` — `python -m app.eval.ragas` CLI; run after full ingest to verify `faithfulness ≥ 0.5`

### Project Constraints
- `CLAUDE.md` — No `openai` import (Embedder Protocol); never split inside a table; `pypdf` primary / `pymupdf4llm` escalation for tables (D-05 refines this: pymupdf4llm is primary given section-awareness need); `youtube-transcript-api` primary / `yt-dlp` fallback; `trafilatura` for articles (not newspaper3k)

### Raw Data
- `raw_data/manuals/` — 15 PDF equipment manuals (source input for INGEST-08)
- `raw_data/youtube_ids.txt` — 13 YouTube video IDs with inline comments (source input for INGEST-10)
- `raw_data/article_urls.txt` — 10 Premier Guitar article URLs (source input for INGEST-09)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/ingest/chunker.py::chunk_forum()` + greedy-pack loop — reuse the same token-budget logic for YouTube and article chunkers (D-09, article Claude's Discretion)
- `app/ingest/chunker.py::Chunk` frozen dataclass — all new source types emit the same `Chunk` type; only `metadata` dict contents differ
- `app/ingest/chunker.py::_ENCODING` (tiktoken `cl100k_base`) — shared across all source types
- `app/ingest/loader.py::RawDocument` — new loaders return `list[RawDocument]`; same contract as `load_forum_posts()`
- `app/ingest/writer.py` — unchanged; all new source types flow through the same writer

### Established Patterns
- `chunk_document()` dispatch on `source_type` — add `elif raw_doc.source_type == "pdf_manual":`, `elif ... == "youtube_transcript":`, `elif ... == "web_article":` branches; remove the `NotImplementedError` fallback once all three are implemented
- `content_hash = sha256(text.encode("utf-8")).hexdigest()` — same dedup mechanism applies to all new source types
- CLAUDE.md Embedder Protocol: all embedding calls via `get_embedder()`, never `import openai`
- Per-document `conn.commit()` for partial durability — applies to new source types in the pipeline loop

### Integration Points
- `app/ingest/pipeline.py::main()` — extend to call `load_pdf_manuals()`, `load_youtube_transcripts()`, `load_web_articles()` and iterate them in sequence after forum posts
- `app/embeddings/factory.py::get_embedder()` — single embedder instance constructed once; passed into the pipeline loop unchanged
- `eval/runs.jsonl` — read by `app/eval/retrieval.py` for diff output; append-only log is written by the eval CLI, not the ingest pipeline

</code_context>

<specifics>
## Specific Ideas

- `youtube_ids.txt` parsing: `line.split("#")[0].strip()` per line; skip empty results
- Article skip threshold: extracted text < 100 words → skip (paywall/boilerplate heuristic)
- End-of-run summary lines: `"PDFs: N of M ingested (K skipped)"` / `"Transcripts: N of M ingested (K skipped)"` / `"Articles: N of M ingested (K skipped)"` — printed after all source types complete
- ToC page heuristic: >50% of lines on a page are short (≤4 whitespace-split tokens) — skip that page
- Eval gate: after full pipeline run, manually execute `python -m app.eval.retrieval` and `python -m app.eval.ragas`; Phase 6 success criteria require `recall@8 ≥ 1.0`, `MRR ≥ 0.9`, `faithfulness ≥ 0.5`

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 6-Full Corpus Ingestion*
*Context gathered: 2026-05-29*
