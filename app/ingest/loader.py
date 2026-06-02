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

This module is pure — it never opens DB connections, never makes network
calls, and never recurses into subdirectories. Path traversal defense is
delegated to ``Path.resolve()`` + ``glob()`` (T-02-01, T-06-03); see the
threat models in 01-02-PLAN.md and 06-02-PLAN.md.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import logging
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
