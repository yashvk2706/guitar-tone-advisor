---
plan: "06-02"
phase: "06-full-corpus-ingestion"
status: complete
completed: "2026-06-01"
requirements_satisfied:
  - INGEST-08
---

# Plan 06-02 Summary: PDF Manual Loader + Chunker

## What Was Built

- `load_pdf_manuals(directory: Path) -> list[RawDocument]` in `app/ingest/loader.py`
  - pymupdf4llm primary extractor (GFM markdown, preserves headings and tables)
  - pypdf fallback on any pymupdf4llm exception
  - Double-failure path: logs WARNING and skips the file — pipeline continues
  - `source_id = str(pdf_path.resolve())` — full absolute path so `chunk_pdf()` can call `pymupdf4llm.to_markdown(raw_doc.source_id, ...)` from any working directory
  - `@functools.lru_cache(maxsize=None)` — parse-once-per-session; all 5 loader tests reuse a single PDF parse pass instead of re-parsing 15 PDFs per test call

- `chunk_pdf(raw_doc: RawDocument) -> list[Chunk]` in `app/ingest/chunker.py`
  - ToC skip heuristic: skips pages where >50% of non-empty lines are ≤4 words
  - Heading detection via `r"^#{1,6}\s+(.+)$"` — section boundaries update `current_heading`
  - Table-atomic rule (D-06): consecutive `|`-prefixed lines collected as one indivisible block; chunk boundary deferred until the entire table block is accumulated
  - Greedy 300–500 token windows (MAX_TOKENS=500) with `_SEPARATOR_TOKENS=1` overhead
  - Forward-merge post-pass: micro-chunks (<40 words) attached to prior chunk
  - Each chunk metadata: `section_heading` (str), `page_number` (int, 1-based), `source_filename` (filename only for display)
  - `chunk_document()` dispatch updated: `elif raw_doc.source_type == "pdf_manual": return chunk_pdf(raw_doc)`

## Tests Added

`tests/test_loader.py` (5 tests, all pass):
- `test_load_pdf_manuals_source_type` — all 15 docs have `source_type == "pdf_manual"`
- `test_load_pdf_manuals_source_id_is_absolute_path` — all source_ids are absolute paths ending `.pdf`
- `test_load_pdf_manuals_count` — exactly 15 RawDocuments returned
- `test_load_pdf_manuals_content_hash_is_hex64` — each hash is 64 lowercase hex chars
- `test_load_pdf_manuals_sorted_order` — deterministic sort by source_id across two calls

`tests/test_chunker.py` (5 tests, all pass):
- `test_pdf_chunker_dispatch` — `chunk_document(pdf_manual doc)` no longer raises NotImplementedError
- `test_pdf_chunker_no_table_split` — table blocks never split across chunk boundaries
- `test_pdf_chunker_skips_cover` — cover page text absent from all chunks
- `test_pdf_chunk_metadata` — every chunk has `section_heading` and `page_number` keys
- `test_pdf_chunks_within_token_budget` — all chunks have `token_count <= 500`

## Key Decisions

- `@functools.lru_cache` added to `load_pdf_manuals` — production code change that also fixes test speed (no conftest fixture needed, no test changes required)
- `source_id` is full absolute path (not filename) — required so `chunk_pdf()` can pass it directly to `pymupdf4llm.to_markdown()` without path reconstruction from any CWD
- Local imports for pymupdf4llm and pypdf inside `load_pdf_manuals` — keeps them optional; import errors surface at call time with a clear message

## Self-Check: PASSED

- `pytest tests/test_loader.py -k pdf` — 5/5 pass
- `pytest tests/test_chunker.py -k pdf` — 5/5 pass
- `grep "pdf_manual" app/ingest/chunker.py` — shows `elif` dispatch to `chunk_pdf()`
- `grep "_is_table_line\|table" app/ingest/chunker.py` — shows table detection logic
- INGEST-08 satisfied (PDF manuals loader + chunker complete)
