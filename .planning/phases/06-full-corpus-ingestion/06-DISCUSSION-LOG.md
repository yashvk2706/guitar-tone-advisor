# Phase 6: Full Corpus Ingestion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-29
**Phase:** 6-Full Corpus Ingestion
**Areas discussed:** PDF chunk granularity, pymupdf4llm escalation trigger, Failure handling, Transcript chunking overlap

---

## PDF Chunk Granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Section-aware | Split on detected headings/sections from pymupdf4llm markdown output | ✓ |
| Page-based windows | Each page = one chunk | |
| Same paragraph-packing as forum | Reuse exact forum chunker logic on extracted text | |

**User's choice:** Section-aware

---

| Option | Description | Selected |
|--------|-------------|----------|
| Pack within section | Use 300–500 token greedy-pack logic within each section | ✓ |
| Allow large sections through | One section = one chunk regardless of size | |

**User's choice:** Pack within section (Recommended)

---

| Option | Description | Selected |
|--------|-------------|----------|
| section_heading + page_number | Tag each chunk with detected section heading and 1-based page number | ✓ |
| page_number only | Just track which page the chunk came from | |
| No extra metadata | source_filename only, same as forum chunker | |

**User's choice:** section_heading + page_number

---

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — skip page 1 + ToC heuristically | Skip first page + pages where >50% lines are short identifiers | ✓ |
| No — ingest all pages | Keep it simple, ingest every page | |

**User's choice:** Yes — skip page 1 + ToC heuristically

---

## pymupdf4llm Escalation Trigger

| Option | Description | Selected |
|--------|-------------|----------|
| pymupdf4llm for all PDFs | Use as primary; pypdf as fallback if pymupdf4llm raises | ✓ |
| pypdf primary, pymupdf4llm per-page | Try pypdf first; re-extract table-heavy pages with pymupdf4llm | |

**User's choice:** pymupdf4llm for all PDFs (Recommended)

---

| Option | Description | Selected |
|--------|-------------|----------|
| Keep pymupdf4llm's markdown table format | GFM tables kept as-is; never split inside a table block | ✓ |
| Convert tables to prose | Flatten to "Row 1: Model=JCM800, Impedance=8Ω" style | |

**User's choice:** Keep pymupdf4llm's markdown table format

---

## Failure Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Skip and log (YouTube) | Log WARNING, continue, print end-of-run summary | ✓ |
| Fail fast (YouTube) | Raise exception and halt pipeline | |

**User's choice:** Skip and log

---

| Option | Description | Selected |
|--------|-------------|----------|
| Try trafilatura, skip if content too short | Attempt extraction; skip if < 100 words | ✓ |
| Skip known paywalled domains | Hardcode a skip list (e.g., /pg-perks/) | |
| Fail fast on 403 | Treat any HTTP error as pipeline failure | |

**User's choice:** Try trafilatura, skip if content too short

---

| Option | Description | Selected |
|--------|-------------|----------|
| Skip and log (PDFs) | Log WARNING with file path + exception, continue to next PDF | ✓ |
| Fail fast (PDFs) | Re-raise exception, halt pipeline | |

**User's choice:** Skip and log

---

## Transcript Chunking Overlap

| Option | Description | Selected |
|--------|-------------|----------|
| Non-overlapping 300–500 token windows | Same greedy-pack as forum chunker | ✓ |
| Sliding windows with 50-token overlap | Each chunk shares 50 tokens with previous chunk | |

**User's choice:** Non-overlapping 300–500 token windows (Recommended)

---

| Option | Description | Selected |
|--------|-------------|----------|
| video_id + start_time | Tag with video ID and start timestamp (seconds) of first segment | ✓ |
| video_id only | Just the video ID in metadata | |
| video_id + title | Fetch title via yt-dlp, more human-readable | |

**User's choice:** video_id + start_time

---

| Option | Description | Selected |
|--------|-------------|----------|
| Strip everything after # | `line.split("#")[0].strip()` per line, skip blank lines | ✓ |
| Require clean IDs only | Raise ValueError if line isn't a pure 11-char YouTube ID | |

**User's choice:** Strip everything after #

---

## Claude's Discretion

- Article chunking granularity: use same greedy 300–500 token paragraph-packing as forum chunker on trafilatura's extracted text; `source_filename` → article URL; no section-aware logic needed for prose articles

## Deferred Ideas

None — discussion stayed within phase scope.
