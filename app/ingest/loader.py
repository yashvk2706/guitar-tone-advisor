"""Forum-post and PDF manual loader.

Reads ``.txt`` files from a corpus directory (the Phase 1 source is
``raw_data/forum_posts/``) and returns a sorted list of ``RawDocument``
dataclasses. Each document is NFKC-normalized once at load time and tagged
with a deterministic sha256 ``content_hash`` so the writer in plan 01-04 can
short-circuit re-ingestion when nothing has changed.

Phase 6 adds ``load_pdf_manuals()`` for the 15 amp/pedal manuals in
``raw_data/manuals/``. Uses ``pymupdf4llm`` as primary extractor with a
``pypdf`` fallback. Corrupt PDFs that fail both extractors are logged and
skipped — the pipeline continues.

Phase 6 Plan 03 adds ``load_youtube_transcripts()`` which reads video IDs
from ``raw_data/youtube_ids.txt``, fetches transcripts via the v1.x
``YouTubeTranscriptApi`` instance API, and falls back to a ``yt-dlp``
subprocess when the primary API fails. Video IDs are validated against
``r'^[A-Za-z0-9_-]{11}$'`` before being passed to the subprocess (T-06-06).
source_type is always ``"youtube"`` — never the transcript library name — to
satisfy the DB CHECK constraint (allowed values: forum, pdf_manual, web_article, youtube).

Phase 6 Plan 04 adds ``load_web_articles()`` which reads URLs from
``raw_data/article_urls.txt``, scrapes each with ``trafilatura``, applies a
100-word minimum threshold for paywall/thin-content detection, and returns
``RawDocument`` instances with ``source_type="web_article"``. The function
guards against ``trafilatura.extract()`` returning ``None`` (T-06-12
mitigation) before any word-count check.

This module is pure — it never opens DB connections and never recurses into
subdirectories. Path traversal defense is delegated to ``Path.resolve()`` +
``glob()`` (T-02-01, T-06-03); see the threat models in 01-02-PLAN.md and
06-02-PLAN.md.
"""

from __future__ import annotations

import dataclasses
import functools
import glob as _glob_module
import hashlib
import logging
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawDocument:
    """Immutable record of one raw corpus file before chunking.

    Attributes:
        source_type: Source family — one of ``"forum"``, ``"pdf_manual"``,
            ``"web_article"``, ``"youtube"``. The DB ``documents`` table has
            a CHECK constraint that enforces this exact set.
        source_id: Filename (e.g. ``"bb_king_tone.txt"``). Stable identifier
            for ``UNIQUE(source_type, source_id)`` in ``documents`` (Plan
            01-04). Must include the ``.txt`` extension so that downstream
            joins through ``chunk_metadata.source_filename`` (D-03) match.
        title: Human-readable title derived from the file stem
            (``"bb_king_tone"`` → ``"Bb King Tone"``). Used only for display
            in the eval-authoring UI (Plan 01-05); ``None`` is permitted for
            future source types that supply their own titles.
        text: Full file content after ``unicodedata.normalize("NFKC", ...)``
            and ``.strip()``. Paragraph separators (blank lines) are
            preserved — the chunker (Plan 01-02 Task 2) splits on them.
        content_hash: ``sha256(text.encode("utf-8")).hexdigest()``. The same
            input bytes always produce the same hash across runs (T-02-03
            mitigation — see Plan 04 idempotent dedup).
        metadata: Optional per-document data for the chunker. Used by the
            YouTube loader to thread snippet ``start`` times into the chunker
            without re-fetching the transcript (e.g.
            ``{"raw_segments": [{"text": ..., "start": 0.0}]}``). Forum,
            PDF, and article loaders leave this as the default empty dict.
    """

    source_type: str
    source_id: str
    title: str | None
    text: str
    content_hash: str
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)


def _normalize(raw: str) -> str:
    """Apply the canonical Phase 1 text normalization.

    NFKC decomposes ligatures (``ﬁ`` → ``fi``) and width variants so the
    chunker, embedder, and eval-author UI all see the same byte sequence
    regardless of how the original forum post was encoded.
    """

    return unicodedata.normalize("NFKC", raw).strip()


def load_forum_posts(directory: Path) -> list[RawDocument]:
    """Load every ``*.txt`` file in ``directory`` as a ``RawDocument``.

    The directory is ``Path.resolve()``-d first so that ``..`` segments are
    collapsed and the subsequent ``glob("*.txt")`` cannot escape the
    intended corpus root (T-02-01 mitigation).

    Returns documents sorted by filename so callers get deterministic
    ordering regardless of the underlying filesystem. Subdirectories are
    ignored (no recursion).

    Args:
        directory: Path to the corpus directory. Must exist and be readable.

    Returns:
        List of ``RawDocument`` instances, one per ``.txt`` file. Empty list
        if the directory contains no ``.txt`` files.
    """

    root = Path(directory).resolve()
    documents: list[RawDocument] = []

    for path in sorted(root.glob("*.txt")):
        # glob("*.txt") matches the resolved root only — files outside
        # `root` are unreachable even when the caller passes `root/..`.
        raw = path.read_text(encoding="utf-8")
        text = _normalize(raw)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        title = path.stem.replace("_", " ").title()
        documents.append(
            RawDocument(
                source_type="forum",
                source_id=path.name,
                title=title,
                text=text,
                content_hash=content_hash,
            )
        )

    return documents


@functools.lru_cache(maxsize=None)
def load_pdf_manuals(directory: Path) -> list[RawDocument]:
    """Load every ``*.pdf`` file in ``directory`` as a ``RawDocument``.

    Uses ``pymupdf4llm`` as the primary extractor to obtain GFM-formatted
    markdown text (preserving headings and table structure for the chunker).
    Falls back to ``pypdf.PdfReader`` if pymupdf4llm raises. If both fail,
    logs a WARNING and skips the file — the pipeline continues.

    The ``source_id`` is the full absolute path (``str(pdf_path.resolve())``)
    so that ``chunk_pdf()`` can pass it directly to
    ``pymupdf4llm.to_markdown()`` from any working directory without a
    ``FileNotFoundError`` (T-06-03 mitigation).

    Args:
        directory: Path to the manuals directory.  Must exist and be readable.

    Returns:
        List of ``RawDocument`` instances sorted by ``source_id``, one per
        ``.pdf`` file.  Empty list if the directory contains no PDFs.
    """

    import pymupdf4llm  # local import — optional heavy dependency
    from pypdf import PdfReader  # local import — optional heavy dependency

    root = Path(directory).resolve()
    documents: list[RawDocument] = []

    for pdf_path in sorted(root.glob("*.pdf")):
        abs_path = pdf_path.resolve()
        text: str | None = None

        # --- Primary extractor: pymupdf4llm (preserves GFM headings/tables) ---
        try:
            pages = pymupdf4llm.to_markdown(str(abs_path), page_chunks=True)
            text = "\n\n".join(p["text"] for p in pages)
        except Exception as primary_exc:
            logger.debug(
                "pymupdf4llm failed for %s: %r — trying pypdf fallback",
                abs_path.name,
                primary_exc,
            )

            # --- Fallback extractor: pypdf (plain text, no markdown) ---
            try:
                reader = PdfReader(str(abs_path))
                page_texts = []
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        page_texts.append(extracted)
                text = "\n\n".join(page_texts)
            except Exception as fallback_exc:
                logger.warning(
                    "PDF load failed %s: %r",
                    abs_path.name,
                    fallback_exc,
                )
                continue  # skip this file; pipeline continues

        normalized = _normalize(text or "")
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        title = abs_path.stem  # raw stem, no titlecasing — e.g. "Marshall JCM800 manual"

        documents.append(
            RawDocument(
                source_type="pdf_manual",
                source_id=str(abs_path),
                title=title,
                text=normalized,
                content_hash=content_hash,
            )
        )

    # Sort by source_id (full absolute path) for deterministic ordering.
    return sorted(documents, key=lambda d: d.source_id)


# ---------------------------------------------------------------------------
# Web article loader (Phase 6 Plan 04, INGEST-09).
# ---------------------------------------------------------------------------

# Module-level import — kept here so tests can patch the names
# `app.ingest.loader.fetch_url` and `app.ingest.loader.extract`.
from trafilatura import extract, fetch_url  # noqa: E402

# Minimum word count threshold for paywall / thin-content detection.
# Articles that fail this gate are logged and skipped (INGEST-09 requirement).
_MIN_ARTICLE_WORDS = 100


def load_web_articles(urls_file: Path) -> list[RawDocument]:
    """Load web articles from a file of URLs using trafilatura.

    Reads ``urls_file`` line by line; strips whitespace; skips blank lines.
    For each URL:

    1. Calls ``trafilatura.fetch_url(url)`` to download the page.
       Skips with WARNING if ``fetch_url`` returns ``None``.
    2. Calls ``trafilatura.extract(downloaded, include_tables=False,
       favor_precision=True)`` to extract the article text.
    3. Guards against ``None`` return (T-06-12 / Pitfall 6 mitigation):
       logs a WARNING and continues — NEVER calls ``text.split()`` on None.
    4. Skips if the extracted text has fewer than ``_MIN_ARTICLE_WORDS``
       whitespace-split words (paywall / thin-content detection).
    5. NFKC-normalizes and strips the text; computes a sha256 content_hash.
    6. Returns ``RawDocument(source_type="web_article", source_id=url, ...)``.
       ``source_id`` is the full URL string (not a filepath) per CONTEXT.md.

    The returned list preserves URL-file order (URLs are not sorted — they
    are a curated list, not a filesystem glob).

    Args:
        urls_file: Path to a newline-delimited file of article URLs.

    Returns:
        List of ``RawDocument`` instances with ``source_type="web_article"``.
        Empty list if all URLs fail download, extraction, or the word-count
        threshold.
    """
    documents: list[RawDocument] = []

    for line in Path(urls_file).read_text(encoding="utf-8").splitlines():
        url = line.strip()
        if not url:
            continue

        # Step 1: download the page.
        downloaded = fetch_url(url)
        if downloaded is None:
            logger.warning("Failed to download %s — skipping", url)
            continue

        # Step 2: extract article text.
        text = extract(downloaded, include_tables=False, favor_precision=True)

        # Step 3: CRITICAL — guard None before any .split() call (T-06-12).
        if text is None:
            logger.warning("Skipping %s: trafilatura returned None", url)
            continue

        # Step 4: word-count threshold.
        word_count = len(text.split())
        if word_count < _MIN_ARTICLE_WORDS:
            logger.warning(
                "Skipping %s: only %d words (< %d threshold)",
                url,
                word_count,
                _MIN_ARTICLE_WORDS,
            )
            continue

        # Step 5: normalize + hash.
        normalized = _normalize(text)
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        # Step 6: build RawDocument.
        documents.append(
            RawDocument(
                source_type="web_article",
                source_id=url,
                title=None,
                text=normalized,
                content_hash=content_hash,
            )
        )

    return documents


# ---------------------------------------------------------------------------
# YouTube transcript loader (Phase 6 Plan 03, INGEST-10).
# ---------------------------------------------------------------------------

# Delayed import at module level — kept here so tests can patch the name
# `app.ingest.loader.YouTubeTranscriptApi`.
from youtube_transcript_api import (  # noqa: E402
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

# 11-char base64url video ID (alphanumeric + hyphen + underscore).
# Validated before any subprocess call to prevent shell injection (T-06-06).
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# VTT timestamp line: HH:MM:SS.mmm --> HH:MM:SS.mmm (with optional position cues).
_VTT_TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s+-->")

# VTT cue ID: a line that is entirely a decimal integer.
_VTT_CUE_ID_RE = re.compile(r"^\d+$")


def _parse_youtube_ids(path: Path) -> list[str]:
    """Parse ``raw_data/youtube_ids.txt`` and return a list of video IDs.

    Lines are stripped of inline comments (everything from ``#`` onward).
    Blank results are skipped.  The returned IDs are all 11-char base64url
    strings — no ``#``, no whitespace.

    Args:
        path: Path to the IDs file (typically ``raw_data/youtube_ids.txt``).

    Returns:
        List of video ID strings in file order.
    """
    ids: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        video_id = line.split("#")[0].strip()
        if video_id:
            ids.append(video_id)
    return ids


def _parse_vtt(vtt_path: str) -> list[dict]:
    """Parse a VTT subtitle file into a list of segment dicts.

    Skips the WEBVTT header line, timestamp lines, cue ID lines, and blank
    lines.  Deduplicates consecutive identical text lines (progressive
    auto-captions repeat the growing sentence on every frame).

    ``yt-dlp`` VTT files do not carry per-segment start times in a machine-
    readable way without a full VTT parser; all segments get ``start=0.0``.

    Args:
        vtt_path: Absolute filesystem path to the ``.vtt`` file.

    Returns:
        List of ``{"text": str, "start": float}`` dicts.  Empty list if the
        file has no usable text content.
    """
    segments: list[dict] = []
    prev_text: str | None = None

    try:
        content = Path(vtt_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("WEBVTT"):
            continue
        if _VTT_TIMESTAMP_RE.match(stripped):
            continue
        if _VTT_CUE_ID_RE.match(stripped):
            continue
        # Deduplicate consecutive identical lines (progressive captions).
        if stripped != prev_text:
            segments.append({"text": stripped, "start": 0.0})
            prev_text = stripped

    return segments


def _load_via_ytdlp(video_id: str) -> "RawDocument | None":
    """Attempt to fetch a YouTube transcript via ``yt-dlp`` as fallback.

    Used when ``YouTubeTranscriptApi`` raises any exception (e.g. geo-block,
    age-gate, or ``TranscriptsDisabled``).

    Security: ``video_id`` is validated against ``_VIDEO_ID_RE`` before it
    is included in the subprocess argument list (T-06-06 mitigation).
    ``subprocess.run`` is always called with ``shell=False`` and an explicit
    list form — never a string form.

    Args:
        video_id: 11-char YouTube video ID.

    Returns:
        A ``RawDocument`` with ``source_type="youtube"`` on success, or
        ``None`` if yt-dlp fails or the VTT file cannot be parsed.
    """
    if not _VIDEO_ID_RE.match(video_id):
        logger.warning("yt-dlp fallback: invalid video_id %r — skipping", video_id)
        return None

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_tmpl = str(Path(tmpdir) / "%(id)s.%(ext)s")
            cmd = [
                "yt-dlp",
                "--cookies-from-browser", "chrome",  # bypasses YouTube IP block with authenticated session
                "--write-auto-subs",
                "--sub-lang", "en",
                "--sub-format", "vtt",
                "--skip-download",
                # --js-runtimes nodejs removed: "nodejs" is wrong value; yt-dlp[default] auto-detects runtime
                f"https://www.youtube.com/watch?v={video_id}",
                "-o", out_tmpl,
            ]
            result = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.warning(
                    "yt-dlp exited %d for %s: %s",
                    result.returncode,
                    video_id,
                    result.stderr[:200],
                )
                return None

            # Find the downloaded VTT file.
            vtt_files = _glob_module.glob(str(Path(tmpdir) / "*.vtt"))
            if not vtt_files:
                logger.warning("yt-dlp produced no .vtt file for %s", video_id)
                return None

            segments = _parse_vtt(vtt_files[0])
            if not segments:
                logger.warning("yt-dlp VTT for %s has no usable text", video_id)
                return None

            full_text = _normalize(" ".join(s["text"] for s in segments))
            content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
            return RawDocument(
                source_type="youtube",
                source_id=video_id,
                title=None,
                text=full_text,
                content_hash=content_hash,
                metadata={"raw_segments": segments},
            )

    except Exception as exc:
        logger.warning("yt-dlp fallback failed for %s: %r", video_id, exc)
        return None


def _build_cookie_session():  # type: ignore[return]
    """Return a requests.Session loaded with Chrome cookies via yt-dlp.

    Used to work around YouTube IP blocks on the primary transcript-API path.
    Returns None silently if cookie extraction fails for any reason.
    """
    try:
        import http.cookiejar
        import tempfile

        import requests as _requests
        import yt_dlp

        tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        tmp.close()
        opts: dict = {"cookiesfrombrowser": ("chrome",), "cookiefile": tmp.name, "quiet": True}
        with yt_dlp.YoutubeDL(opts):
            pass
        jar = http.cookiejar.MozillaCookieJar(tmp.name)
        jar.load(ignore_discard=True, ignore_expires=True)
        session = _requests.Session()
        session.cookies = jar  # type: ignore[assignment]
        return session
    except Exception as exc:
        logger.debug("Cookie session build failed: %r — proceeding without cookies", exc)
        return None


def load_youtube_transcripts(ids_file: Path) -> list[RawDocument]:
    """Load YouTube transcripts for all video IDs in ``ids_file``.

    Primary path: ``YouTubeTranscriptApi().fetch(video_id)`` (v1.x instance
    API — NOT the removed static ``get_transcript()`` method).

    Fallback: ``_load_via_ytdlp(video_id)`` when the primary raises any
    exception.

    Videos that fail both primary and fallback are logged as WARNING and
    skipped.  The pipeline always continues.

    Args:
        ids_file: Path to the video IDs file (``raw_data/youtube_ids.txt``).
            Inline comments (``# ...``) are stripped per D-11.

    Returns:
        List of ``RawDocument`` instances with ``source_type="youtube"``.
        ``metadata["raw_segments"]`` carries a list of
        ``{"text": str, "start": float}`` dicts for the chunker to consume.
    """
    video_ids = _parse_youtube_ids(Path(ids_file))
    # Export Chrome cookies so YouTubeTranscriptApi can bypass IP-based blocks.
    cookie_session = _build_cookie_session()
    api = YouTubeTranscriptApi(http_client=cookie_session) if cookie_session else YouTubeTranscriptApi()
    documents: list[RawDocument] = []

    for video_id in video_ids:
        doc: RawDocument | None = None

        # --- Primary: youtube-transcript-api ---
        try:
            transcript = api.fetch(video_id)
            segments = [{"text": snippet.text, "start": snippet.start} for snippet in transcript]
            full_text = _normalize(" ".join(s["text"] for s in segments))
            content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
            doc = RawDocument(
                source_type="youtube",
                source_id=video_id,
                title=None,
                text=full_text,
                content_hash=content_hash,
                metadata={"raw_segments": segments},
            )
        except Exception as primary_exc:
            logger.warning(
                "youtube-transcript-api failed for %s: %r — trying yt-dlp fallback",
                video_id,
                primary_exc,
            )
            doc = _load_via_ytdlp(video_id)

        if doc is None:
            logger.warning("All transcript sources failed for %s — skipping", video_id)
            continue

        documents.append(doc)

    return documents
