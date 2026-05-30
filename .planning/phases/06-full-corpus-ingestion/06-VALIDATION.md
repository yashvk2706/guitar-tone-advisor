---
phase: 6
slug: full-corpus-ingestion
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-29
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 |
| **Config file** | none — run via `pytest tests/` |
| **Quick run command** | `venv/bin/python -m pytest tests/test_loader.py tests/test_chunker.py tests/test_writer.py -x` |
| **Full suite command** | `venv/bin/python -m pytest tests/ -x` |
| **Estimated runtime** | ~15 seconds (offline; no network calls) |

---

## Sampling Rate

- **After every task commit:** Run `venv/bin/python -m pytest tests/test_loader.py tests/test_chunker.py tests/test_writer.py -x`
- **After every plan wave:** Run `venv/bin/python -m pytest tests/ -x`
- **Before `/gsd-verify-work`:** Full suite must be green + manual eval gate (`python -m app.eval.retrieval --held-out`)
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | INGEST-08/09/10 | T-06-01 | upsert_chunks stores source_type from parameter, not hardcoded "forum" | unit | `pytest tests/test_writer.py::test_upsert_chunks_uses_source_type -x` | ❌ W0 | ⬜ pending |
| 06-01-02 | 01 | 1 | INGEST-08/09/10 | — | RawDocument.metadata field exists and defaults to {} | unit | `pytest tests/test_loader.py::test_rawdocument_metadata_field -x` | ❌ W0 | ⬜ pending |
| 06-02-01 | 02 | 2 | INGEST-08 | T-06-03 | load_pdf_manuals() returns RawDocuments with absolute source_id paths | unit | `pytest tests/test_loader.py -k "pdf" -x` | ❌ W0 | ⬜ pending |
| 06-02-02 | 02 | 2 | INGEST-08 | T-06-04 | chunk_pdf() never splits inside a GFM table block | unit | `pytest tests/test_chunker.py::test_pdf_chunker_no_table_split -x` | ❌ W0 | ⬜ pending |
| 06-03-01 | 03 | 2 | INGEST-10 | T-06-06 | YouTube source_type is "youtube" not "youtube_transcript" | unit | `pytest tests/test_loader.py::test_youtube_source_type -x` | ❌ W0 | ⬜ pending |
| 06-03-02 | 03 | 2 | INGEST-10 | — | YouTube chunk metadata carries video_id and start_time | unit | `pytest tests/test_chunker.py::test_youtube_chunk_metadata -x` | ❌ W0 | ⬜ pending |
| 06-04-01 | 04 | 3 | INGEST-09 | — | Article loader skips None or <100-word extracts | unit | `pytest tests/test_loader.py::test_article_loader_skip_none_extract -x` | ❌ W0 | ⬜ pending |
| 06-04-02 | 04 | 3 | INGEST-09 | — | Article chunk metadata source_filename equals URL | unit | `pytest tests/test_chunker.py::test_article_chunk_metadata -x` | ❌ W0 | ⬜ pending |
| 06-05-01 | 05 | 4 | INGEST-08/09/10 | — | Pipeline passes source_type to upsert_chunks for all 4 source types | unit | `pytest tests/test_pipeline.py -x` | ❌ W0 | ⬜ pending |
| 06-05-02 | 05 | 4 | EVAL-05 | — | recall@8 ≥ 1.0 and MRR ≥ 0.9 on held-out set after full ingest | integration (manual) | `python -m app.eval.retrieval --held-out` | ✅ Phase 5 | ⬜ pending |
| 06-05-03 | 05 | 4 | EVAL-05 | — | faithfulness ≥ 0.5 after full ingest | integration (manual) | `python -m app.eval.ragas` | ✅ Phase 5 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_writer.py` — add `test_upsert_chunks_uses_source_type` (verifies writer fix in Plan 01)
- [ ] `tests/test_loader.py` — add tests for PDF loader (5 tests), YouTube loader (ID parser + source_type + metadata), article loader (skip/none handling)
- [ ] `tests/test_chunker.py` — add tests for PDF (table-atomic, cover skip, metadata, dispatch, token budget), YouTube (chunk metadata + start_time), article (metadata)
- [ ] `tests/test_pipeline.py` — add tests for full pipeline source_type dispatch (offline, no DB/network)
- [ ] `requirements.txt` — add `pymupdf4llm==0.0.25 pypdf==5.9.0 youtube-transcript-api==1.2.4 yt-dlp trafilatura==2.0.0`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| recall@8 ≥ 1.0, MRR ≥ 0.9 on held-out set | EVAL-05 | Requires full pipeline run + live DB + live embedder | 1. Run `python -m app.ingest.pipeline`; 2. Run `python -m app.eval.retrieval --held-out`; 3. Check output for recall@8 and MRR values |
| faithfulness ≥ 0.5 on sampled answers | EVAL-05 | Requires live Anthropic API calls | 1. Run `python -m app.eval.ragas`; 2. Check mean_faithfulness in output |
| End-of-run summary lines printed | INGEST-08/09/10 | Requires full pipeline run | Confirm "PDFs: N of M ingested (K skipped)", "Transcripts: N of M ingested (K skipped)", "Articles: N of M ingested (K skipped)" appear in stdout |
| chunk count grows from 21 to ≥200 | INGEST-08/09/10 | Requires live DB | `psql $DATABASE_URL -c "SELECT COUNT(*) FROM chunks;"` — must show ≥200 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
