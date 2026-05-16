"""Forum-post loader.

Reads ``.txt`` files from a corpus directory (the Phase 1 source is
``raw_data/forum_posts/``) and returns a sorted list of ``RawDocument``
dataclasses. Each document is NFKC-normalized once at load time and tagged
with a deterministic sha256 ``content_hash`` so the writer in plan 01-04 can
short-circuit re-ingestion when nothing has changed.

This module is pure — it never opens DB connections, never makes network
calls, and never recurses into subdirectories. Path traversal defense is
delegated to ``Path.resolve()`` + ``glob("*.txt")`` (T-02-01); see the
threat model in 01-02-PLAN.md.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RawDocument:
    """Immutable record of one raw corpus file before chunking.

    Attributes:
        source_type: Source family. For Phase 1 this is always ``"forum"``;
            Phase 2 introduces ``"pdf_manual"``, ``"web_article"``,
            ``"youtube_transcript"``.
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
    """

    source_type: str
    source_id: str
    title: str | None
    text: str
    content_hash: str


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
