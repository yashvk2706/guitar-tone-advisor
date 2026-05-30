# Phase 6: Full Corpus Ingestion - Research

**Researched:** 2026-05-29
**Domain:** Python document ingestion — PDF (pymupdf4llm + pypdf), YouTube transcripts (youtube-transcript-api + yt-dlp), web articles (trafilatura)
**Confidence:** HIGH (library APIs verified via official docs and PyPI; codebase analysis via direct file reads)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**PDF Chunking Strategy**
- D-01: Section-aware chunking using heading detection from `pymupdf4llm`'s markdown output. `#`/`##` heading lines delineate manual sections; each section boundary starts a new chunk group.
- D-02: Within each section, apply the same greedy 300–500 token paragraph-packing logic as the forum chunker (tiktoken `cl100k_base`, `MAX_TOKENS=500`). A section too large for one chunk gets split into sub-chunks with the same `section_heading`.
- D-03: PDF chunk metadata includes `section_heading` (detected heading text or `""` for pre-heading content) and `page_number` (1-based). `source_filename` stays as in Phase 1.
- D-04: Skip first page unconditionally (cover art/title page). Skip any page where >50% of its text lines are short identifier-only content (ToC entries). Prevents ToC/cover pollution.
- D-05: Use `pymupdf4llm` as the **primary** extractor for all PDFs — its markdown output is required for heading detection. `pypdf` acts as fallback: if `pymupdf4llm` raises, retry with `pypdf` plain-text extraction + paragraph-packing. (`section_heading=""` for all chunks in fallback path.)
- D-06: Tables from `pymupdf4llm` are kept in GFM markdown table format (`| col | col |`) as-is. CLAUDE.md hard constraint ("never split inside a table") is honored because `pymupdf4llm` emits the complete table as a single markdown block — the chunker must not split that block.

**Failure Handling (all source types)**
- D-07: Skip-and-log for all three new source types. Log `WARNING` with resource identifier and reason, continue to next item. Run succeeds as long as at least one item per source type is processed.
  - YouTube: `youtube-transcript-api` primary, `yt-dlp` fallback. If both fail, log and skip. End-of-run summary: `"Transcripts: N of M videos ingested (K skipped)"`.
  - Articles: `trafilatura.fetch_url()` + `trafilatura.extract()`. If extracted text is under 100 words, log and skip. End-of-run summary: `"Articles: N of M URLs ingested (K skipped)"`.
  - PDFs: If `pymupdf4llm` and `pypdf` fallback both raise, log and skip. End-of-run summary: `"PDFs: N of M files ingested (K skipped)"`.
- D-08: The pipeline does not fail the run when individual items are skipped. It only exits non-zero if an unrecoverable error occurs (DB connection failure, embedder error).

**YouTube Transcript Chunking**
- D-09: Non-overlapping 300–500 token windows, same greedy-pack budget as forum chunker. No sliding window overlap.
- D-10: YouTube chunk metadata carries `video_id` (11-char ID from the file) and `start_time` (float, seconds from start of video for the first caption segment in the window).
- D-11: Parse `raw_data/youtube_ids.txt` line by line: strip everything after `#`, strip whitespace, skip blank lines. `line.split("#")[0].strip()` per line.

**Article Chunking**
- Claude's Discretion: Same greedy 300–500 token paragraph-packing logic as forum chunker on trafilatura's extracted text. `source_filename` → article URL. No section-aware chunking.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INGEST-08 | Ingestion pipeline processes PDF equipment manuals from `raw_data/manuals/` (15 PDFs) with section-aware chunking that never splits inside a table | D-01 through D-06; pymupdf4llm `to_markdown(page_chunks=True)` API verified |
| INGEST-09 | Ingestion pipeline scrapes and extracts text from 10 Premier Guitar article URLs with rate-limiting and paywall detection | trafilatura `fetch_url()` + `extract()` API verified; 100-word skip threshold from D-07 |
| INGEST-10 | Ingestion pipeline fetches and processes transcripts for 13 YouTube video IDs with time-window chunking | youtube-transcript-api 1.2.4 `YouTubeTranscriptApi().fetch()` API verified; yt-dlp subprocess fallback pattern verified |
| EVAL-05 | After full ingest, recall@8 ≥ 1.0, MRR ≥ 0.9, faithfulness ≥ 0.5 on held-out set | `python -m app.eval.retrieval` and `python -m app.eval.ragas` CLIs are already implemented (Phase 5); eval gate is manual execution after pipeline run |

</phase_requirements>

---

## Summary

Phase 6 adds three new `load_*` functions to `app/ingest/loader.py` and three new `chunk_*` functions to `app/ingest/chunker.py`, then extends `pipeline.py` to call all four source types in sequence. All three new source types share the same `Chunk` frozen dataclass, the same `content_hash = sha256(text.encode()).hexdigest()` dedup mechanism, and the same per-document `conn.commit()` partial-durability pattern established in Phase 1.

The central discovery is a **writer bug that Phase 6 must fix**: `app/ingest/writer.py::upsert_chunks()` hardcodes `_PHASE_1_SOURCE_TYPE = "forum"` on line 142 and uses it for every chunk regardless of source type. The comment in the file explicitly documents "Phase 2 will pass the source_type through from the RawDocument when PDF/web/youtube chunkers come online." Phase 6 is that moment — `upsert_chunks()` must accept and use the true `raw_doc.source_type`, and `pipeline.py` must pass it through.

A second discovery is a **naming inconsistency**: `loader.py` docs say `"youtube_transcript"`, but `init_db.sql` has a CHECK constraint `source_type IN ('forum','pdf_manual','web_article','youtube')` — `"youtube_transcript"` would violate that constraint. The correct value is `"youtube"` (matching `app/retrieval/base.py` which annotates the field as `'youtube'`). The new YouTube loader must emit `source_type="youtube"`.

The eval gate (EVAL-05) is manual: run `python -m app.eval.retrieval` and `python -m app.eval.ragas` after the full pipeline run. The retrieval scorer and RAGAS CLI are already fully implemented from Phase 5. The 5 held-out queries test BB King, Eddie Van Halen, funk pickup, lo-fi tone, and Mark Knopfler topics — topics covered by both forum posts and the new PDF manuals and YouTube transcripts, so the ≥1.0 recall@8 target is realistic once the corpus grows from 21 to ≥200 chunks.

**Primary recommendation:** Fix the `writer.py` source_type hardcode first, then implement loaders and chunkers in dependency order (PDF → YouTube → Articles), then wire pipeline, then run and verify.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| PDF text extraction | Offline CLI (ingest) | — | `pymupdf4llm` is a local library call; runs offline during pipeline |
| PDF heading detection | Offline CLI (ingest) | — | Markdown heading regex applied to `pymupdf4llm` text output |
| YouTube transcript fetch | Offline CLI (ingest) | — | `youtube-transcript-api` makes network calls at ingest time, not query time |
| Article scraping | Offline CLI (ingest) | — | `trafilatura` downloads pages at ingest time; API is read-only at query time |
| Chunk embedding | Offline CLI (ingest) | — | OpenAI embeddings via Embedder Protocol; all new source types use same embedder |
| DB write (documents + chunks) | Offline CLI (ingest) | — | `writer.py` unchanged; all new source types use same upsert functions |
| Retrieval (eval gate) | API / Backend | — | `app/retrieval/base.py::retrieve()` used by both API and eval scorer |
| Eval scoring | Offline CLI (eval) | — | `app/eval/retrieval.py` and `app/eval/ragas.py` run post-ingest |

---

## Standard Stack

### Core (new dependencies for Phase 6)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pymupdf4llm` | 0.0.25 (latest on this Python 3.x/pip env) | PDF → GFM markdown conversion | Official PyMuPDF LLM extension; emits GFM tables; heading detection via `#` markers; section-aware chunking |
| `pypdf` | 5.9.0 (latest) | PDF fallback plain-text extraction | Pure Python; stable; CLAUDE.md explicitly names it as fallback |
| `youtube-transcript-api` | 1.2.4 (CLAUDE.md pinned) | Fetch YouTube transcripts | No API key required; handles auto-generated captions; Python-native |
| `yt-dlp` | latest stable (2024.10.x range) | YouTube fallback caption extraction | Subprocess-based; produces VTT files parseable by standard tools |
| `trafilatura` | 2.0.0 (CLAUDE.md pinned) | Web article boilerplate removal + text extraction | State-of-the-art boilerplate removal; returns `str | None` on failure |

**Note on pymupdf4llm versioning:** The pip registry shows only versions `0.0.1` through `0.0.25` available for the project's Python environment. The PyPI page advertises `1.27.2.3` (released April 2026), which requires Python ≥ 3.10 and a newer PyMuPDF. The project's venv is Python 3.x — use `0.0.25` which is the latest installable version. [VERIFIED: pip registry query]

### Supporting (already present)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tiktoken` | 0.12.0 | Token counting for 300–500 window sizing | Used in all new chunkers via shared `_ENCODING = tiktoken.get_encoding("cl100k_base")` |
| `tenacity` | 9.1.4 | Retry/backoff wrapper | Wrap `trafilatura.fetch_url()` and embedder calls; already wraps OpenAI embedder |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pymupdf4llm` (primary) | `pdfminer`, `pdfplumber` | Neither emits GFM tables or heading markers; CLAUDE.md mandates `pymupdf4llm` for table-heavy manuals |
| `trafilatura` | `newspaper3k`, `beautifulsoup4` | `newspaper3k` is abandoned (CLAUDE.md explicit non-dep); BS4 gives raw HTML, not cleaned text |
| `youtube-transcript-api` | YouTube Data API v3 | Data API requires API key + quota; `youtube-transcript-api` is keyless |
| `yt-dlp` subprocess | `yt-dlp` Python API directly | Both are viable; subprocess is simpler and avoids internal API instability |

**Installation:**
```bash
pip install pymupdf4llm==0.0.25 pypdf==5.9.0 youtube-transcript-api==1.2.4 yt-dlp trafilatura==2.0.0
```

---

## Architecture Patterns

### System Architecture Diagram

```
raw_data/
├── forum_posts/*.txt     → load_forum_posts()    ┐
├── manuals/*.pdf         → load_pdf_manuals()    ├── RawDocument list
├── youtube_ids.txt       → load_youtube_transcripts() ┘
└── article_urls.txt      → load_web_articles()   ┘

                          chunk_document() dispatch on source_type
                               │
                    ┌──────────┼──────────────┬────────────────┐
                    ▼          ▼              ▼                ▼
             chunk_forum() chunk_pdf()  chunk_youtube()  chunk_article()
                    │          │              │                │
                    └──────────┴──────────────┴────────────────┘
                                      │
                               list[Chunk]
                                      │
                               chunks_to_embed()  ← content_hash dedup
                                      │
                               embedder.embed_documents()  ← OpenAI via Protocol
                                      │
                               upsert_chunks(source_type=raw_doc.source_type)  ← FIXED
                                      │
                              PostgreSQL + pgvector
                                      │
                              python -m app.eval.retrieval  ← EVAL-05 gate
                              python -m app.eval.ragas
```

### Recommended Project Structure

```
app/ingest/
├── loader.py          # + load_pdf_manuals(), load_youtube_transcripts(), load_web_articles()
├── chunker.py         # + chunk_pdf(), chunk_youtube(), chunk_article(); dispatch updated
├── pipeline.py        # extended: 4 source-type loops; end-of-run summaries
└── writer.py          # fix: remove _PHASE_1_SOURCE_TYPE hardcode; accept source_type param

tests/
├── test_loader.py     # + tests for 3 new loaders (offline; no network mocks needed for parsing)
└── test_chunker.py    # + tests for 3 new chunkers (offline; test on real or synthetic text)
```

### Pattern 1: pymupdf4llm Page-Chunk Extraction

**What:** Extract PDF as list of per-page dicts with GFM markdown text.
**When to use:** Primary path for all PDFs; gives `page["text"]` with heading markers and pipe tables.

```python
# Source: https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html
import pymupdf4llm

pages: list[dict] = pymupdf4llm.to_markdown(
    str(pdf_path),
    page_chunks=True,  # returns list[dict] instead of one big str
)
# Each dict has keys: "metadata" (includes "page_number" 1-based), "text" (Markdown str)
for page in pages:
    page_number: int = page["metadata"]["page_number"]  # 1-based
    md_text: str = page["text"]  # GFM markdown, tables as | col | ... |
```

**Key facts:** [VERIFIED: pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html]
- `page_chunks=True` returns `list[dict]`, one dict per page
- Each dict's `"metadata"` key contains `"page_number"` (1-based integer)
- Each dict's `"text"` key contains the page's Markdown content including GFM pipe tables
- Tables are rendered as `| col | col |` pipe-table rows in `"text"` — they appear as a single contiguous block within one page's text; the chunker must treat any `|`-starting line block as an atomic unit (D-06)
- `pages=[0, 1, 2]` parameter (0-based list) controls which pages to process — use this to skip page 0 (cover) instead of skipping in post-processing

### Pattern 2: Heading Detection from GFM Markdown

**What:** Detect `#`/`##` heading lines from pymupdf4llm output to drive section-aware chunking.
**When to use:** PDF chunker (D-01). Each heading line starts a new section.

```python
import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

def detect_heading(line: str) -> str | None:
    """Return heading text if line is a Markdown heading, else None."""
    m = re.match(r"^#{1,6}\s+(.+)$", line.rstrip())
    return m.group(1).strip() if m else None
```

[ASSUMED] — Heading detection via regex on `#` prefix is the natural pattern given pymupdf4llm's GFM output; exact heading levels from real guitar manual PDFs are not verified in this session.

### Pattern 3: youtube-transcript-api 1.2.4 Fetch

**What:** Fetch a transcript as an iterable of `FetchedTranscriptSnippet` objects.
**When to use:** Primary path for YouTube loader.

```python
# Source: https://github.com/jdepoix/youtube-transcript-api
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api import (
    TranscriptsDisabled,
    VideoUnavailable,
    NoTranscriptFound,
)

api = YouTubeTranscriptApi()
try:
    transcript = api.fetch(video_id)  # returns FetchedTranscript (iterable)
    for snippet in transcript:
        text: str = snippet.text
        start: float = snippet.start       # seconds from video start (NOT start_time)
        duration: float = snippet.duration # seconds
except (TranscriptsDisabled, VideoUnavailable, NoTranscriptFound) as e:
    logger.warning("Skipping %s: %r", video_id, e)
```

**Key facts:** [VERIFIED: github.com/jdepoix/youtube-transcript-api, pypi.org/project/youtube-transcript-api/]
- Version 1.2.4 is the latest release (January 29, 2026) — matches CLAUDE.md pin
- Old API `YouTubeTranscriptApi.get_transcript(video_id)` is removed in 1.x; use `YouTubeTranscriptApi().fetch(video_id)`
- Snippet attribute is `snippet.start` (float, seconds), NOT `start_time`
- D-10 metadata key should be stored as `start_time` in the chunk metadata, populated from `snippet.start` of the first snippet in each window
- Additional catchable exceptions: `IpBlocked`, `RequestBlocked`, `AgeRestricted`, `VideoUnplayable`, `PoTokenRequired` — catch `Exception` for the broader yt-dlp fallback trigger

### Pattern 4: yt-dlp Fallback (Subprocess)

**What:** Download auto-generated captions as VTT file, then parse the file's text.
**When to use:** Only when `youtube-transcript-api` raises any exception.

```python
# Source: https://medium.com/@jallenswrx2016/using-yt-dlp-to-download-youtube-transcript-...
import subprocess
import tempfile
import glob
import re

def fetch_via_ytdlp(video_id: str) -> list[dict] | None:
    """Returns list of {'text': str, 'start': float} or None on failure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_tmpl = f"{tmpdir}/%(id)s"
        cmd = [
            "yt-dlp",
            "--write-auto-subs",
            "--sub-lang", "en",
            "--sub-format", "vtt",
            "--skip-download",
            f"https://www.youtube.com/watch?v={video_id}",
            "-o", out_tmpl,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return None
        vtt_files = glob.glob(f"{tmpdir}/*.vtt")
        if not vtt_files:
            return None
        return _parse_vtt(vtt_files[0])

def _parse_vtt(path: str) -> list[dict]:
    """Parse VTT file into [{text, start}]. Deduplicate progressive captions."""
    # VTT auto-captions have duplicate lines; deduplicate by timestamp key.
    ...
```

[VERIFIED: subprocess approach from medium.com/@jallenswrx2016] [ASSUMED: exact VTT deduplication pattern — YouTube auto-generated VTT files have progressive caption lines that need deduplication before tokenization]

**Critical:** `yt-dlp` must be installed and available on `$PATH`. See Environment Availability section.

### Pattern 5: trafilatura Article Extraction

**What:** Download and boilerplate-strip a web article to plain text.
**When to use:** Article loader for all URLs in `article_urls.txt`.

```python
# Source: https://trafilatura.readthedocs.io/en/latest/corefunctions.html
from trafilatura import fetch_url, extract

downloaded: str | None = fetch_url(url)
if downloaded is None:
    logger.warning("Failed to download %s", url)
    return None

text: str | None = extract(downloaded, include_tables=False, favor_precision=True)
if text is None or len(text.split()) < 100:
    logger.warning("Skipping %s: insufficient text (%d words)", url, len(text.split()) if text else 0)
    return None
```

**Key facts:** [VERIFIED: trafilatura.readthedocs.io/en/latest/corefunctions.html]
- `fetch_url(url)` returns `str | None`; None on download failure
- `extract(filecontent)` returns `str | None`; None when extraction fails (not empty string)
- `include_tables=False` avoids including HTML table text which may be noisy for this corpus
- `favor_precision=True` — prefer less text but correct extraction (better for paywall/thin content detection)
- No built-in paywall detection; the 100-word threshold from D-07 is the project's heuristic
- Default timeout is 30 seconds (CLI mode); in programmatic use, no timeout is enforced by default — `fetch_url` inherits whatever the underlying urllib timeout is [ASSUMED: exact timeout behavior in programmatic use]

### Pattern 6: Greedy-Pack Token Window (reuse from chunk_forum)

**What:** The same 300–500 token greedy paragraph-packing loop used in `chunk_forum()`, applied to YouTube snippet text and article paragraphs.
**When to use:** YouTube chunker (D-09) and article chunker (Claude's Discretion).

The exact algorithm from `app/ingest/chunker.py::chunk_forum()` [VERIFIED: direct codebase read]:
1. Split text on blank lines into blocks
2. Pre-compute tokens per block via `_ENCODING.encode(block)`
3. Greedy accumulate: if adding next block keeps total ≤ 500 tokens, append; else close current chunk and start new
4. Account for `_SEPARATOR_TOKENS = 1` per join (the `\n\n` separator encodes to ~1 token)
5. Forward-merge post-pass: micro-chunks (<40 words) attach to prior chunk

**For YouTube:** Replace paragraph split with caption segment grouping. Snippets are the atomic units; group them greedily until the token budget is reached. `start_time` in metadata = `snippet.start` of the first snippet in the window.

### Anti-Patterns to Avoid

- **Splitting inside a GFM table:** Do not split any chunk mid-table. In pymupdf4llm output, a table appears as a run of `|`-prefixed lines. The PDF chunker must detect this block and never insert a chunk boundary inside it. (D-06; CLAUDE.md hard constraint)
- **Using `"youtube_transcript"` as source_type:** The DB `documents` CHECK constraint only allows `'youtube'`. Using `"youtube_transcript"` raises a Postgres constraint violation. (Verified in `scripts/init_db.sql`)
- **Using `_PHASE_1_SOURCE_TYPE = "forum"` for new chunks:** The `upsert_chunks()` function currently hardcodes `source_type='forum'` for all chunks. This must be fixed before Phase 6 loaders run or all new chunks will be tagged as forum posts.
- **Importing `openai` directly:** CLAUDE.md hard constraint. All embedding via `get_embedder()`.
- **Calling `embed_query()` on corpus text:** CLAUDE.md hard constraint. Use `embed_documents()` for corpus passages, `embed_query()` only for retrieval-time query embedding.
- **Treating `trafilatura.extract()` returning `None` as empty string:** Always check `if text is None` before word counting or chunking.
- **Skipping the `snippet.start` attribute:** The attribute is `.start` (float, seconds), not `.start_time`. Storing it in chunk metadata as `"start_time"` key is fine, but the source attribute name is `.start`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PDF text extraction | Custom PDF parser | `pymupdf4llm.to_markdown()` | Tables, headings, multi-column layout handling is extremely complex |
| PDF table detection | Regex on raw text | `pymupdf4llm` table detection | Table boundaries require spatial layout analysis, not text patterns |
| Boilerplate removal | HTML tag stripping with regex | `trafilatura.extract()` | Boilerplate detection uses ML classifiers trained on thousands of pages |
| YouTube caption fetch | YouTube HTML scraping | `youtube-transcript-api` | YouTube constantly changes its internal API; the library tracks these changes |
| VTT parsing | Raw string parsing | Parse known VTT structure (start/end/text blocks) | Simple enough to hand-roll for the fallback path; no heavy parser needed |
| Token counting for windows | word count heuristic | `_ENCODING.encode(text)` (`tiktoken cl100k_base`) | Word count is inaccurate for code and proper nouns; token count matches embedding model |

**Key insight:** The hard problem in this phase is not calling the APIs — it is correctly handling the multi-page PDF structure (heading continuity across pages, table preservation) and the greedy-pack window sizing (identical token budget across all 4 source types so retrieval quality is consistent).

---

## Writer Fix: Critical Pre-Condition

This is the single most important finding of this research. Before any new source type can be correctly stored, `app/ingest/writer.py` must be patched.

### Current (broken for Phase 6)

```python
# writer.py line 142-195
_PHASE_1_SOURCE_TYPE = "forum"  # hardcoded

params = [
    (
        str(uuid.uuid5(_CHUNK_NS, c.content_hash)),
        document_id,
        _PHASE_1_SOURCE_TYPE,  # WRONG: always 'forum'
        ...
    )
]
```

### Required Fix

`upsert_chunks()` must accept a `source_type: str` parameter and use it in the params tuple. The pipeline must pass `raw_doc.source_type` to `upsert_chunks()`.

```python
def upsert_chunks(
    conn: psycopg.Connection,
    document_id: str,
    chunks: Sequence[Chunk],
    vectors: Sequence[Sequence[float]],
    embedding_model: str,
    source_type: str,          # NEW — passed from raw_doc.source_type
) -> int:
    ...
    params = [
        (
            str(uuid.uuid5(_CHUNK_NS, c.content_hash)),
            document_id,
            source_type,        # now correct for all source types
            ...
        )
    ]
```

The existing `test_writer.py` tests all use `source_type="forum"` implicitly — they will need to be checked to ensure they still pass after the signature change (the default or required arg change may break tests that don't pass `source_type`).

---

## Source Type Name Constraint

**Critical:** The DB `documents` table has a CHECK constraint:

```sql
source_type IN ('forum','pdf_manual','web_article','youtube')
```

The loader must use **exactly** these strings:

| Source | `source_type` value | Notes |
|--------|---------------------|-------|
| Forum posts | `"forum"` | Existing; unchanged |
| PDF manuals | `"pdf_manual"` | New |
| Web articles | `"web_article"` | New |
| YouTube transcripts | `"youtube"` | NOT `"youtube_transcript"` — DB constraint |

The `loader.py` docstring says `"youtube_transcript"` — this is wrong per the schema. The new YouTube loader must use `"youtube"`. [VERIFIED: `scripts/init_db.sql` CHECK constraint; `app/retrieval/base.py` ChunkResult annotation]

---

## Common Pitfalls

### Pitfall 1: youtube_transcript vs youtube source_type
**What goes wrong:** New YouTube loader sets `source_type="youtube_transcript"`, triggering a Postgres CHECK constraint violation on the `documents` table. The pipeline logs an error and fails the document upsert.
**Why it happens:** `loader.py` docstring and CONTEXT.md use `"youtube_transcript"` but the DB schema uses `"youtube"`.
**How to avoid:** Hardcode `source_type="youtube"` in `load_youtube_transcripts()`. Add a test that verifies the string exactly.
**Warning signs:** `psycopg.errors.CheckViolation` during document upsert.

### Pitfall 2: _PHASE_1_SOURCE_TYPE hardcode in writer
**What goes wrong:** All PDF, article, and YouTube chunks are stored with `source_type='forum'` in the `chunks` table, making them indistinguishable from forum posts in retrieval metadata and CITE-02 source-type label rendering.
**Why it happens:** `writer.py` has `_PHASE_1_SOURCE_TYPE = "forum"` hardcoded as a Phase 1 placeholder, with a comment saying Phase 2 would fix it (never did).
**How to avoid:** Fix `upsert_chunks()` signature before implementing any new loader. Make this the first task of Wave 1.
**Warning signs:** After pipeline run, `SELECT DISTINCT source_type FROM chunks` returns only `{'forum'}`.

### Pitfall 3: Table splitting in PDF chunker
**What goes wrong:** A GFM table `| col | col |` block straddles the chunk boundary; retrieval returns half a table, confusing the LLM and preventing faithful citations.
**Why it happens:** The greedy-pack loop checks token budget without awareness of `|`-line blocks.
**How to avoid:** Before starting a new chunk, check if the current block starts with `|`. If mid-table, defer the chunk boundary until the table block ends. A table block ends at the first non-`|` non-empty line.
**Warning signs:** Retrieved chunks containing `| ... |` on the last line but missing the table header.

### Pitfall 4: Page 1 skipping via pages parameter vs post-processing
**What goes wrong:** Skip logic is applied after extraction, making the page 0 text still tokenized and potentially leaking into a chunk.
**How to avoid:** Use `pymupdf4llm.to_markdown(pdf_path, page_chunks=True, pages=list(range(1, n_pages)))` to skip page index 0 (cover page) at extraction time. The `pages` parameter is 0-based.
**Warning signs:** Chunks containing "Model XYZ User Manual" or table-of-contents entries with page numbers like `Chapter 1 … 3`.

### Pitfall 5: youtube-transcript-api v1.x API change
**What goes wrong:** Code calls `YouTubeTranscriptApi.get_transcript(video_id)` (v0.x static method), which was removed in v1.0.0.
**Why it happens:** Most tutorials and SO answers predate v1.0.0 (March 2025).
**How to avoid:** Always use `YouTubeTranscriptApi().fetch(video_id)` — instantiate the class first.
**Warning signs:** `AttributeError: type object 'YouTubeTranscriptApi' has no attribute 'get_transcript'`.

### Pitfall 6: trafilatura extract() returning None silently
**What goes wrong:** `None.split()` raises `AttributeError` when checking word count.
**Why it happens:** `extract()` returns `None` (not `""`) when it can't find meaningful content — e.g., on paywalled pages or JavaScript-only pages.
**How to avoid:** Always guard: `if text is None or len(text.split()) < 100: skip`.
**Warning signs:** `AttributeError: 'NoneType' object has no attribute 'split'`.

### Pitfall 7: yt-dlp VTT auto-captions have duplicate lines
**What goes wrong:** Auto-generated YouTube VTT captions repeat lines with overlapping timestamps (progressive display). Concatenating raw VTT text results in doubled content.
**Why it happens:** YouTube progressively appends words with overlapping time ranges in auto-captions.
**How to avoid:** Deduplicate consecutive identical text lines when parsing VTT output. Keep only unique text lines in temporal order.
**Warning signs:** Chunks with phrases like "so you want" followed immediately by "so you want to get" (word-by-word overlap).

### Pitfall 8: Writer test breakage from signature change
**What goes wrong:** Existing `test_writer.py` calls `upsert_chunks(conn, doc_id, chunks, vectors, model)` without `source_type` argument, causing `TypeError` after the fix.
**Why it happens:** The signature change adds a required parameter.
**How to avoid:** Either add `source_type` as a keyword argument with a default of `"forum"` for backward compatibility (safe), or update all call sites in tests simultaneously.
**Warning signs:** `TypeError: upsert_chunks() missing 1 required positional argument: 'source_type'` in `test_writer.py`.

---

## Code Examples

### PDF Loader Pattern

```python
# Source: codebase analysis of load_forum_posts() + pymupdf4llm official docs
import hashlib
import unicodedata
from pathlib import Path
import pymupdf4llm

from app.ingest.loader import RawDocument

def load_pdf_manuals(directory: Path) -> list[RawDocument]:
    root = Path(directory).resolve()
    docs = []
    for pdf_path in sorted(root.glob("*.pdf")):
        try:
            pages: list[dict] = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)
            # Join all pages' text for the document-level content_hash
            full_text = "\n\n".join(p["text"] for p in pages)
            full_text = unicodedata.normalize("NFKC", full_text).strip()
            content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
            docs.append(RawDocument(
                source_type="pdf_manual",
                source_id=pdf_path.name,          # e.g. "Fender Twin Reverb Manual.pdf"
                title=pdf_path.stem,
                text=full_text,                    # stored for dedup; chunker re-reads pages
                content_hash=content_hash,
            ))
        except Exception as e:
            logger.warning("PDF load failed %s: %r", pdf_path.name, e)
    return docs
```

**Note:** The PDF chunker receives the full text but needs per-page metadata (page_number, table positions). The cleanest implementation calls `pymupdf4llm.to_markdown(page_chunks=True)` again inside `chunk_pdf()` rather than threading the page list through `RawDocument`. Alternative: add a `metadata` field to `RawDocument` and store the page list there. Either approach works — the planner should pick one consistently. [ASSUMED: The metadata approach avoids re-reading the file; the re-read approach keeps RawDocument simple]

### YouTube Loader Pattern

```python
# Source: github.com/jdepoix/youtube-transcript-api README
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, VideoUnavailable, NoTranscriptFound

def load_youtube_transcripts(ids_file: Path) -> list[RawDocument]:
    video_ids = _parse_youtube_ids(ids_file)
    api = YouTubeTranscriptApi()
    docs = []
    for video_id in video_ids:
        try:
            transcript = api.fetch(video_id)
            # Build text for dedup hash; chunker will re-iterate snippets
            segments = [{"text": s.text, "start": s.start} for s in transcript]
            full_text = " ".join(s["text"] for s in segments)
            full_text = unicodedata.normalize("NFKC", full_text).strip()
            content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
            docs.append(RawDocument(
                source_type="youtube",             # NOT "youtube_transcript"
                source_id=video_id,
                title=None,
                text=full_text,
                content_hash=content_hash,
                # The chunks need start times — see metadata design note below
            ))
        except Exception as e:
            logger.warning("YouTube failed %s: %r — trying yt-dlp", video_id, e)
            doc = _load_via_ytdlp(video_id)
            if doc:
                docs.append(doc)
    return docs

def _parse_youtube_ids(path: Path) -> list[str]:
    ids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        vid = line.split("#")[0].strip()   # D-11: strip inline comments
        if vid:
            ids.append(vid)
    return ids
```

**Design note for `start_time` in chunk metadata:** The `RawDocument.text` field concatenates snippet text for the document-level hash. But the YouTube chunker needs `snippet.start` per segment to populate `metadata["start_time"]`. Two options:
1. Store the raw segments list in `RawDocument.metadata` dict (added field — needs RawDocument modification)  
2. Re-call `api.fetch(video_id)` inside the chunker (requires passing video_id through, and makes chunker network-dependent)

Option 1 is cleaner. `RawDocument` already has `metadata: dict` implied by context (though not in the current frozen dataclass — it has no `metadata` field). The current `RawDocument` dataclass is: `source_type`, `source_id`, `title`, `text`, `content_hash`. A `metadata: dict[str, Any] = field(default_factory=dict)` field needs to be added, or the segments stored as a pickle/JSON in a new field. [ASSUMED: This design decision is left to the planner — simplest is adding a `raw_segments` list field to RawDocument for YouTube only]

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `YouTubeTranscriptApi.get_transcript(id)` static method | `YouTubeTranscriptApi().fetch(id)` instance method | v1.0.0 (March 2025) | All 0.x tutorial code is broken; must use instance API |
| `import fitz` for PyMuPDF | `import pymupdf` (fitz still works as alias) | PyMuPDF 1.24+ | `fitz` still available but `pymupdf` is canonical; `pymupdf4llm` uses pymupdf internally |
| `trafilatura.extract()` with `no_fallback=True` | `fast=True` parameter replaces `no_fallback` | trafilatura 2.0 | `no_fallback` is deprecated; use `fast=True` for equivalent behavior |

**Deprecated/outdated:**
- `YouTubeTranscriptApi.get_transcript()`: Removed in 1.x. Use instance method `.fetch()`.
- `_PHASE_1_SOURCE_TYPE = "forum"` constant in `writer.py`: Explicitly marked for Phase 2 removal; Phase 6 removes it.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | pymupdf4llm tables never span page boundaries (the table is always emitted as a single block within one page's text) | Common Pitfalls §3, Code Examples | If tables CAN span pages in some PDF layouts, the table-boundary check in the chunker will fail to prevent mid-table splits |
| A2 | `pymupdf4llm.to_markdown(page_chunks=True)` emits headings as `# Heading Text` lines in the `"text"` field for guitar manual PDFs (the manuals have clear section headings like Controls, Specifications) | Pattern 1, D-01 | If manuals use bold/font-size-based headings that pymupdf4llm converts to bold `**text**` instead of `# text`, the heading detector won't find sections |
| A3 | VTT deduplication of progressive YouTube auto-captions is needed; consecutive identical-text lines should be collapsed | Pitfall 7 | If the 13 YouTube videos all have well-formed SRT-style captions (one line per timestamp, no overlap), deduplication adds unnecessary complexity |
| A4 | `trafilatura.fetch_url()` has no configurable timeout in programmatic (non-CLI) use; network hangs are possible | Pattern 5 | A hung fetch_url() call blocks the pipeline indefinitely on a slow URL; a timeout wrapper (e.g. signal.alarm or concurrent.futures.ThreadPoolExecutor with timeout) may be needed |
| A5 | The `RawDocument` dataclass needs a new field (`raw_segments` or `metadata`) to thread YouTube snippet start times into the chunker without re-fetching | Code Examples design note | If the design is to call `api.fetch()` again inside the chunker, the chunker becomes network-dependent and harder to unit-test |
| A6 | The 15 PDF manuals in `raw_data/manuals/` are text-based PDFs (not scanned images), so pymupdf4llm text extraction will work without OCR | Environment §PDF | If any manual is a scanned image PDF, `pymupdf4llm` returns empty text and the fallback `pypdf` will also fail; OCR would be needed (out of scope for Phase 6) |

---

## Open Questions

1. **Table spanning page boundaries in pymupdf4llm**
   - What we know: pymupdf4llm detects tables and renders them as GFM pipe-table rows in the page text. The `page_chunks=True` output has one dict per page.
   - What's unclear: Whether a table that physically spans two pages in the PDF is split across two page dicts or joined into one.
   - Recommendation: Test with `Mesa Boogie Mark V manual.pdf` (likely has multi-page specs tables) at Wave 0. If tables split across pages, the chunker needs a cross-page table continuation check.

2. **RawDocument dataclass: add `metadata` field or not?**
   - What we know: The current `RawDocument` dataclass has no `metadata` dict field. YouTube chunking needs snippet `start` times that come from the loader.
   - What's unclear: Whether the planner wants to modify `RawDocument` (affects all existing code paths) or re-fetch in the chunker (cleaner separation but network dependency).
   - Recommendation: Add `metadata: dict[str, Any] = dataclasses.field(default_factory=dict)` to `RawDocument` (frozen dataclass needs `field()` for mutable default). YouTube loader stores `{"raw_segments": [{"text": ..., "start": ...}]}`. Other loaders leave `metadata={}`. This is the minimal-change approach.

3. **yt-dlp PATH availability**
   - What we know: `yt-dlp` is not in the venv (not in `requirements.txt`); it needs to be installed separately.
   - What's unclear: Whether it should be in `requirements.txt` or installed as a system tool.
   - Recommendation: Add `yt-dlp` to `requirements.txt` so `pip install -r requirements.txt` makes it available. It installs a CLI command.

4. **EVAL-05 realistic target: recall@8 ≥ 1.0 on held-out set**
   - What we know: The 5 held-out queries are on BB King, EVH signal chain, funk pickup, lo-fi, and Mark Knopfler. The current 21-chunk forum-only corpus achieves some non-zero baseline recall. Adding 200+ chunks from manuals (Marshall JCM800, Fender, Boss, Ibanez TS9), YouTube transcripts (SRV tone, Mark Knopfler, funk rhythm, EVH gear), and articles should introduce many more relevant chunks.
   - What's unclear: Whether the specific held-out chunk IDs in `golden_set.jsonl` (forum chunk UUIDs) are still the "expected" chunks, or whether better-matching manual/YouTube chunks will be added to the golden set.
   - Recommendation: Recall@8 requires at least ONE expected chunk to appear in the top 8 — the held-out forum chunks should still be retrievable after expansion. The target is realistic. No golden-set modification is needed (deferred per CONTEXT.md scope).

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `pymupdf4llm` | INGEST-08 | Not installed | — (need install) | None for primary; `pypdf` is the per-file fallback |
| `pypdf` | INGEST-08 fallback | Not installed | — (need install) | None (must install) |
| `youtube-transcript-api` | INGEST-10 | Not installed | — (need install) | `yt-dlp` subprocess |
| `yt-dlp` | INGEST-10 fallback | Not installed | — (need install) | Skip video with WARNING |
| `trafilatura` | INGEST-09 | Not installed | — (need install) | None (must install) |
| PostgreSQL | All | Assumed running | Local | — |
| `pytest` | Test suite | 9.0.3 (in venv) | 9.0.3 | — |
| OpenAI API key | Embedding | Present (.env) | — | — |

[VERIFIED: `pip install X==99.0` probe for each package; venv `pip show` check]

**Missing dependencies with no fallback (must install before Wave 1 implementation):**
- `pymupdf4llm==0.0.25` — primary PDF extractor; no alternative
- `pypdf==5.9.0` — PDF fallback; explicitly named in CLAUDE.md
- `trafilatura==2.0.0` — article scraper; `newspaper3k` is banned (CLAUDE.md)

**Missing dependencies with fallback:**
- `youtube-transcript-api==1.2.4` — primary; fallback is yt-dlp subprocess
- `yt-dlp` (latest) — YouTube fallback; if absent, videos that fail youtube-transcript-api are skipped with WARNING

**Wave 0 install command:**
```bash
pip install pymupdf4llm==0.0.25 pypdf==5.9.0 youtube-transcript-api==1.2.4 yt-dlp trafilatura==2.0.0
```

Then update `requirements.txt` with pinned versions.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | none — tests run via `pytest tests/` |
| Quick run command | `pytest tests/test_chunker.py tests/test_loader.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-08 | PDF loader returns `RawDocument` with `source_type="pdf_manual"` | unit | `pytest tests/test_loader.py::test_load_pdf_manuals -x` | ❌ Wave 0 |
| INGEST-08 | PDF chunker never splits inside a GFM table block | unit | `pytest tests/test_chunker.py::test_pdf_chunker_no_table_split -x` | ❌ Wave 0 |
| INGEST-08 | PDF chunker skips page 0 (cover) | unit | `pytest tests/test_chunker.py::test_pdf_chunker_skips_cover -x` | ❌ Wave 0 |
| INGEST-08 | PDF chunker populates `section_heading` and `page_number` in metadata | unit | `pytest tests/test_chunker.py::test_pdf_chunk_metadata -x` | ❌ Wave 0 |
| INGEST-09 | Article loader skips URLs yielding <100 words | unit | `pytest tests/test_loader.py::test_article_loader_skip_short -x` | ❌ Wave 0 |
| INGEST-09 | Article chunker produces chunks with `source_filename` = URL | unit | `pytest tests/test_chunker.py::test_article_chunk_metadata -x` | ❌ Wave 0 |
| INGEST-10 | YouTube ID parser strips comments and blank lines (D-11) | unit | `pytest tests/test_loader.py::test_parse_youtube_ids -x` | ❌ Wave 0 |
| INGEST-10 | YouTube chunk metadata carries `video_id` and `start_time` | unit | `pytest tests/test_chunker.py::test_youtube_chunk_metadata -x` | ❌ Wave 0 |
| INGEST-10 | YouTube source_type is `"youtube"` not `"youtube_transcript"` | unit | `pytest tests/test_loader.py::test_youtube_source_type -x` | ❌ Wave 0 |
| INGEST-06 | Dedup holds for PDF chunks (content_hash unchanged on re-run) | unit | `pytest tests/test_writer.py::test_pdf_dedup -x` | ❌ Wave 0 |
| writer fix | `upsert_chunks` stores correct source_type per chunk | unit | `pytest tests/test_writer.py::test_upsert_chunks_uses_source_type -x` | ❌ Wave 0 |
| EVAL-05 | recall@8 ≥ 1.0, MRR ≥ 0.9 after full ingest | integration (manual) | `python -m app.eval.retrieval --held-out` | ✅ (from Phase 5) |
| EVAL-05 | faithfulness ≥ 0.5 after full ingest | integration (manual) | `python -m app.eval.ragas` | ✅ (from Phase 5) |

### Sampling Rate
- **Per task commit:** `pytest tests/test_chunker.py tests/test_loader.py tests/test_writer.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green + manual `python -m app.eval.retrieval` shows recall@8 ≥ 1.0

### Wave 0 Gaps

- [ ] `tests/test_loader.py` — new test functions for PDF, YouTube, and article loaders (unit tests, offline; use synthetic text not real network calls)
- [ ] `tests/test_chunker.py` — new test functions for PDF, YouTube, and article chunkers (unit tests, offline; synthesize markdown-with-table input for PDF tests)
- [ ] `tests/test_writer.py` — new test for `upsert_chunks` `source_type` parameter (verifies the writer fix)
- [ ] `requirements.txt` — add `pymupdf4llm==0.0.25 pypdf==5.9.0 youtube-transcript-api==1.2.4 yt-dlp trafilatura==2.0.0`

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | Validate PDF paths via `Path.resolve()` + `glob`; validate YouTube IDs as 11-char alphanumeric; validate URLs before passing to trafilatura |
| V6 Cryptography | no | content_hash is SHA-256 for dedup, not security; no cryptographic requirements |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal in `raw_data/manuals/` | Tampering | `Path.resolve()` + `glob("*.pdf")` — same pattern as `load_forum_posts()` |
| Shell injection via video_id in yt-dlp subprocess | Tampering | Validate `video_id` is exactly 11 alphanumeric+hyphen+underscore chars before passing to subprocess; use `subprocess.run([...], shell=False)` (list form, not string) |
| SSRF via article_urls.txt | Spoofing | URLs are in a committed file; trafilatura fetches them as-is; acceptable for a single-user local tool |
| F-string SQL in new pipeline code | Tampering | All SQL via `%s` placeholders — static test in `test_writer.py::test_no_fstring_sql_in_writer` already enforces this |

---

## Sources

### Primary (HIGH confidence)
- [pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html) — `to_markdown()` full signature, `page_chunks=True` return structure, `pages` parameter
- [github.com/jdepoix/youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) — v1.x API shape, `FetchedTranscriptSnippet` fields (`.text`, `.start`, `.duration`), exception class names
- [trafilatura.readthedocs.io/en/latest/corefunctions.html](https://trafilatura.readthedocs.io/en/latest/corefunctions.html) — `fetch_url()` and `extract()` signatures, return type `str | None`
- [pypi.org/project/youtube-transcript-api/](https://pypi.org/project/youtube-transcript-api/) — version 1.2.4 confirmed as latest
- [pypi.org/project/pymupdf4llm/](https://pypi.org/project/pymupdf4llm/) — latest on PyPI advertised as 1.27.2.3 (Python ≥3.10); installable in project env is 0.0.25
- `app/ingest/writer.py`, `app/ingest/chunker.py`, `app/ingest/loader.py`, `app/ingest/pipeline.py`, `scripts/init_db.sql`, `app/retrieval/base.py` — direct codebase reads confirming writer bug, source_type naming, and existing patterns
- pip registry version probe — confirmed package version ranges available in project environment

### Secondary (MEDIUM confidence)
- [deepwiki.com/pymupdf/pymupdf4llm/1.2-installation-and-dependencies](https://deepwiki.com/pymupdf/pymupdf4llm/1.2-installation-and-dependencies) — PyMuPDF ≥1.26.6 dependency requirement
- [github.com/jdepoix/youtube-transcript-api/blob/master/youtube_transcript_api/_transcripts.py](https://github.com/jdepoix/youtube-transcript-api/blob/master/youtube_transcript_api/_transcripts.py) — exception class inventory

### Tertiary (LOW confidence)
- [medium.com/@jallenswrx2016/using-yt-dlp-to-download-youtube-transcript-...](https://medium.com/@jallenswrx2016/using-yt-dlp-to-download-youtube-transcript-3479fccad9ea) — yt-dlp subprocess pattern with `--write-auto-subs --sub-format vtt --skip-download`
- General web search results on pymupdf4llm table GFM format and cross-page behavior — partially unverified; flagged as ASSUMED in Assumptions Log

---

## Metadata

**Confidence breakdown:**
- Standard stack (library APIs): HIGH — verified via official docs and PyPI
- Architecture (writer fix, source_type naming): HIGH — verified by direct codebase reads
- pymupdf4llm table behavior (cross-page): LOW — official docs do not specify; flagged ASSUMED
- yt-dlp fallback VTT parsing: MEDIUM — subprocess approach verified; deduplication pattern ASSUMED
- Eval gate realism (recall@8 ≥ 1.0): MEDIUM — based on corpus content reasoning, not empirical test

**Research date:** 2026-05-29
**Valid until:** 2026-06-28 (30 days; `youtube-transcript-api` is the most volatile — YouTube can break it without a library update)
