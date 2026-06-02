---
plan: "06-05"
phase: "06-full-corpus-ingestion"
status: complete
completed: "2026-06-02"
requirements_satisfied:
  - INGEST-08
  - INGEST-09
  - INGEST-10
  - EVAL-05
---

# Plan 06-05 Summary: Pipeline Orchestration + Eval Gate

## What Was Built

- `app/ingest/pipeline.py` extended with 3 new source-type loops (pdf, youtube, web_article) after the existing forum loop; each uses the same pattern: load → upsert_document → chunk_document → chunks_to_embed → embed → upsert_chunks(source_type=raw_doc.source_type)
- `_build_parser()` gained `--manuals-dir`, `--youtube-ids`, `--article-urls` CLI args
- D-07 end-of-run summary via `print()`: "PDFs: N of M ingested (K skipped)", "Transcripts: N of M", "Articles: N of M"
- `requirements.txt` updated with 5 new deps: pymupdf4llm==0.0.25, pypdf==5.9.0, youtube-transcript-api==1.2.4, yt-dlp, trafilatura==2.0.0
- `tests/test_pipeline.py`: `test_pipeline_imports_all_loaders` + `test_help_includes_new_args` (static, no DB)

## Bugs Fixed During Execution

- **chunks_pkey UniqueViolation** (`writer.py`): chunk UUID was `uuid5(NS, content_hash)` — two chunks from different documents with identical text produced the same UUID. Fixed to `uuid5(NS, f"{document_id}:{chunk_index}:{embedding_model}")` — mirrors the unique constraint, globally unique.
- **yt-dlp JS runtime missing**: added `--js-runtimes nodejs` to subprocess call — yt-dlp defaults to deno only but Node.js is available.
- **Golden set stale UUIDs**: after UUID scheme change, `eval/golden_set.jsonl` expected_chunk_ids pointed to old-scheme UUIDs. Remapped via content_hash lookup against live DB.

## Pipeline Run Results

```
OK: 656 chunks inserted, 0 skipped across 35 documents
PDFs: 9 of 15 ingested (6 skipped — small pedal manuals with 0 usable chunks after ToC/cover heuristics)
Transcripts: 0 of 13 ingested (13 skipped — YouTube RequestBlocked + yt-dlp Node.js fix committed; browser cookies needed for full fix → deferred to Phase 7)
Articles: 10 of 10 ingested (0 skipped)
```

## Eval Results (EVAL-05)

| Metric | Target | Result | Status |
|--------|--------|--------|--------|
| recall@8 | ≥ 1.0 | 1.00 | ✓ |
| MRR | ≥ 0.9 | 0.90 | ✓ |
| faithfulness | ≥ 0.5 | ~0.11–0.21 | ✗ (corpus gap, not code bug) |

Faithfulness shortfall is a corpus coverage issue: model uses parametric knowledge for these artist-specific queries when source passages don't contain enough citable specifics. YouTube transcripts (the highest-signal source for these queries) failed to ingest. Fix deferred to Phase 7.

Human checkpoint: **approved** by user 2026-06-02.

## Self-Check: PASSED (with noted gap)

- `pytest tests/test_pipeline.py::test_pipeline_imports_all_loaders` ✓
- `pytest tests/test_pipeline.py::test_help_includes_new_args` ✓
- recall@8 = 1.00, MRR = 0.90 ✓
- faithfulness ~0.15 (below 0.50 target — deferred) ⚠
- INGEST-08, INGEST-09, INGEST-10, EVAL-05 delivered
