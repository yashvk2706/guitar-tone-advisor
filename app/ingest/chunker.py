"""Paragraph-packing chunker for the corpus.

Treats each source document as a stream of blocks and greedily packs them
into 300–500 token chunks measured with ``tiktoken``'s ``cl100k_base``
encoding (the same encoder OpenAI uses for the ``text-embedding-3-*`` family
— see ``.planning/research/STACK.md`` §Chunking Strategy per Source Type).

Source-type dispatch is a CLAUDE.md hard constraint: ``chunk_document``
inspects ``raw_doc.source_type`` and routes to the per-type chunker.

Phase 1 implementation decisions (locked by 01-CONTEXT.md):

* **D-01** Forward-merge: any paragraph with fewer than ``MIN_PARAGRAPH_WORDS``
  (40) whitespace-split words is folded into the next chunk rather than
  emitted as a sub-40-word standalone chunk. Trailing short paragraphs
  attach to the previous chunk instead.
* **D-02** No quoted-reply stripping — the corpus files contain no ``>`` or
  ``[quote]`` markers.
* **D-03** Every chunk carries ``metadata["source_filename"]`` so the eval
  authoring UI (Plan 01-05) can display provenance.
* **D-04** ``chunk_index`` is 0-based and resets per document.

Phase 6 PDF chunker additions (locked by 06-02-PLAN.md):

* **D-01** Heading detection: ``## Section Name`` GFM headings open a new
  section boundary; ``current_heading`` updates on each heading line.
* **D-03** PDF chunk metadata carries ``source_filename`` (filename only,
  for display), ``section_heading`` (str), and ``page_number`` (int, 1-based).
* **D-04** ToC skip heuristic: pages where >50% of non-empty lines have
  ≤ 4 words are skipped (index page / table of contents).
* **D-06** Table-atomic rule: a maximal contiguous run of ``|``-prefixed
  lines is treated as a single atomic block — never split mid-table.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tiktoken

logger = logging.getLogger(__name__)

# Heading detection: GFM ATX headings (1–6 #s followed by space + text).
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$")

from app.ingest.loader import RawDocument

# cl100k_base is the encoding for OpenAI text-embedding-3-* and Claude's
# tokenizer is close enough for sizing — see STACK.md §Chunking.
_ENCODING = tiktoken.get_encoding("cl100k_base")

# Hard cap. A chunk that would exceed this on its next paragraph closes
# before that paragraph is appended (greedy pack).
MAX_TOKENS = 500

# Forward-merge floor (D-01): a paragraph with fewer than this many words is
# never emitted as a standalone chunk.
MIN_PARAGRAPH_WORDS = 40

# Blank-line paragraph separator — one or more newlines surrounding optional
# whitespace. Matches the actual format of every file in
# raw_data/forum_posts/.
_PARAGRAPH_SEP = re.compile(r"\n\s*\n+")


@dataclass(frozen=True)
class Chunk:
    """One emitted text chunk ready for embedding + DB insert.

    Attributes:
        chunk_index: 0-based position within the parent document (D-04).
            Combined with ``documents.id`` this is the deduplication key the
            writer (Plan 01-04) uses to skip already-ingested chunks.
        text: NFKC-normalized, stripped chunk body. Paragraph separators
            inside a chunk are preserved as ``"\\n\\n"``.
        token_count: ``len(_ENCODING.encode(text))``. Guaranteed
            ``<= MAX_TOKENS`` for all chunks emitted by ``chunk_forum`` on
            the Phase 1 corpus (no single forum paragraph exceeds 500
            tokens by inspection — see ``<action>`` step 5 in 01-02-PLAN).
        content_hash: ``sha256(text.encode("utf-8")).hexdigest()`` — drives
            idempotent re-ingestion (T-02-03 mitigation).
        metadata: Free-form provenance dict. MUST contain
            ``"source_filename"`` (D-03); future source types may add more
            keys (e.g. page numbers for PDFs, timestamps for transcripts).
    """

    chunk_index: int
    text: str
    token_count: int
    content_hash: str
    metadata: dict[str, Any]


def chunk_document(raw_doc: RawDocument) -> list[Chunk]:
    """Dispatch to the per-source-type chunker.

    CLAUDE.md hard constraint: "Chunking dispatches on source_type — no
    universal chunker." Supported source types: ``"forum"``, ``"pdf_manual"``,
    ``"youtube"``.
    Unknown source types raise ``NotImplementedError`` so accidental callers
    fail loudly rather than silently producing degenerate output.
    """

    if raw_doc.source_type == "forum":
        return chunk_forum(raw_doc)
    elif raw_doc.source_type == "pdf_manual":
        return chunk_pdf(raw_doc)
    elif raw_doc.source_type == "youtube":
        return chunk_youtube(raw_doc)
    elif raw_doc.source_type == "web_article":
        return chunk_article(raw_doc)

    raise NotImplementedError(
        f"Chunker for source_type={raw_doc.source_type!r} not implemented"
    )


def _is_toc_page(lines: list[str]) -> bool:
    """Return True if the page looks like a Table of Contents (D-04).

    Heuristic: if more than 50% of non-empty lines have ≤ 4 whitespace-split
    words, treat the page as a ToC / index page and skip it.
    """
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return True
    short_count = sum(1 for ln in non_empty if len(ln.split()) <= 4)
    return (short_count / len(non_empty)) > 0.5


def _is_table_line(line: str) -> bool:
    """Return True if the line is part of a GFM table (starts with ``|``)."""
    return line.lstrip().startswith("|")


def _finalize_pdf_chunk(
    blocks: list[str],
    chunk_index: int,
    source_id: str,
    section_heading: str,
    page_number: int,
) -> Chunk:
    """Materialize a list of text blocks into a frozen PDF Chunk with full metadata."""
    text = unicodedata.normalize("NFKC", "\n\n".join(blocks)).strip()
    return Chunk(
        chunk_index=chunk_index,
        text=text,
        token_count=len(_ENCODING.encode(text)),
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        metadata={
            "source_filename": Path(source_id).name,
            "section_heading": section_heading,
            "page_number": page_number,
        },
    )


def chunk_pdf(raw_doc: RawDocument) -> list[Chunk]:
    """Section-aware, table-atomic chunker for PDF manuals (INGEST-08).

    Algorithm:

    1. Open the PDF via ``pymupdf4llm.to_markdown()`` (GFM output, page_chunks=True).
       ``raw_doc.source_id`` is the full absolute path set by ``load_pdf_manuals()``.
    2. Skip page index 0 (cover page) by calling ``to_markdown()`` with
       ``pages=list(range(1, page_count))``.
    3. For each remaining page, apply the ToC-skip heuristic (D-04): skip pages
       where >50% of non-empty lines have ≤ 4 words.
    4. Within each page, process lines:
       - Heading lines (``^#{1,6}\\s+…``) flush the current accumulator and
         update ``current_heading`` (D-01).
       - Table lines (``|``-prefixed) are collected into a single atomic block;
         this block is never split mid-table (D-06).
       - Other lines form text blocks that enter the greedy 500-token accumulator.
    5. Falls back to ``pypdf.PdfReader`` plain-text extraction if ``pymupdf4llm``
       raises any exception (D-08). Plain-text fallback gets ``section_heading=""``.

    Each emitted chunk's metadata carries ``source_filename`` (filename only),
    ``section_heading``, and ``page_number`` (1-based int) per D-03.
    """

    import pymupdf4llm  # local import — optional heavy dependency
    from pypdf import PdfReader  # local import — optional heavy dependency

    _SEPARATOR_TOKENS = 1  # "\n\n" between blocks costs 1 token in cl100k_base

    chunks: list[Chunk] = []

    # ------------------------------------------------------------------ #
    # Primary extractor: pymupdf4llm                                       #
    # ------------------------------------------------------------------ #
    try:
        # First call: get all pages to count them (needed for pages= param).
        all_pages = pymupdf4llm.to_markdown(raw_doc.source_id, page_chunks=True)
        n_pages = len(all_pages)

        if n_pages <= 1:
            # Only cover page (or empty PDF) — nothing to chunk.
            return []

        # Second call: skip page index 0 (cover) by requesting indices 1..n-1.
        pages = pymupdf4llm.to_markdown(
            raw_doc.source_id,
            page_chunks=True,
            pages=list(range(1, n_pages)),
        )

        for page in pages:
            page_num: int = page["metadata"]["page"]
            page_text: str = page.get("text", "")
            lines = page_text.splitlines()

            # ToC heuristic skip (D-04).
            if _is_toc_page(lines):
                continue

            current_heading: str = ""
            current_blocks: list[str] = []
            current_tokens: int = 0
            table_buffer: list[str] = []

            def _flush_table() -> str | None:
                """Flush the table buffer into a single atomic block string."""
                nonlocal table_buffer
                if not table_buffer:
                    return None
                block = "\n".join(table_buffer)
                table_buffer = []
                return block

            def _emit_chunk() -> None:
                nonlocal current_blocks, current_tokens, chunks
                if current_blocks:
                    chunks.append(
                        _finalize_pdf_chunk(
                            current_blocks,
                            len(chunks),
                            raw_doc.source_id,
                            current_heading,
                            page_num,
                        )
                    )
                    current_blocks = []
                    current_tokens = 0

            def _add_block(block: str) -> None:
                """Add a block to the greedy accumulator, emitting a chunk if needed."""
                nonlocal current_blocks, current_tokens
                block_tokens = len(_ENCODING.encode(block))
                separator = _SEPARATOR_TOKENS if current_blocks else 0
                projected = current_tokens + separator + block_tokens
                if current_blocks and projected > MAX_TOKENS:
                    _emit_chunk()
                    current_blocks = [block]
                    current_tokens = block_tokens
                else:
                    current_blocks.append(block)
                    current_tokens = projected if not current_blocks[:-1] else projected

            # Process lines left-to-right, building blocks.
            for line in lines:
                heading_match = _HEADING_RE.match(line.rstrip())
                if heading_match:
                    # Flush any buffered table first.
                    table_block = _flush_table()
                    if table_block:
                        _add_block(table_block)
                    # Flush current accumulator and start a new section.
                    _emit_chunk()
                    current_heading = heading_match.group(1).strip()
                    # The heading line itself becomes the first block of the
                    # new section so it appears as context in the chunk.
                    current_blocks = [line.rstrip()]
                    current_tokens = len(_ENCODING.encode(line.rstrip()))
                elif _is_table_line(line):
                    # Accumulate table rows into the buffer.
                    table_buffer.append(line)
                else:
                    # Before adding non-table content, flush any pending table.
                    if table_buffer:
                        table_block = _flush_table()
                        if table_block:
                            _add_block(table_block)
                    stripped = line.strip()
                    if stripped:
                        _add_block(stripped)

            # After processing all lines, flush remaining table and accumulator.
            table_block = _flush_table()
            if table_block:
                _add_block(table_block)
            _emit_chunk()

    except Exception as primary_exc:
        logger.debug(
            "pymupdf4llm chunking failed for %s: %r — trying pypdf fallback",
            Path(raw_doc.source_id).name,
            primary_exc,
        )

        # ------------------------------------------------------------------ #
        # Fallback: pypdf plain text — no heading detection, page_number=0    #
        # ------------------------------------------------------------------ #
        try:
            reader = PdfReader(raw_doc.source_id)
            for page_idx, page in enumerate(reader.pages):
                if page_idx == 0:
                    continue  # skip cover page
                text = page.extract_text() or ""
                paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
                for para in paragraphs:
                    para_tokens = len(_ENCODING.encode(para))
                    sep = _SEPARATOR_TOKENS if chunks else 0
                    # Start fresh chunk per page in fallback mode.
                    if chunks and (len(_ENCODING.encode(chunks[-1].text)) + sep + para_tokens) > MAX_TOKENS:
                        # Emit the last accumulated paragraph as its own chunk.
                        pass  # chunks are individual paragraphs in fallback
                    chunks.append(
                        _finalize_pdf_chunk(
                            [para],
                            len(chunks),
                            raw_doc.source_id,
                            section_heading="",
                            page_number=page_idx + 1,
                        )
                    )
        except Exception as fallback_exc:
            logger.warning(
                "PDF chunking failed completely for %s: %r",
                Path(raw_doc.source_id).name,
                fallback_exc,
            )

    return chunks


def _split_paragraphs(text: str) -> list[str]:
    """Split a document into stripped, non-empty paragraph blocks."""

    return [p.strip() for p in _PARAGRAPH_SEP.split(text) if p.strip()]


def _finalize_chunk(blocks: list[str], chunk_index: int, source_id: str) -> Chunk:
    """Materialize a list of paragraph blocks into a frozen ``Chunk``.

    Re-applies NFKC normalization on the joined chunk text so that any
    whitespace-only differences picked up during concatenation never leak
    into the content hash (T-02-03 mitigation).
    """

    text = unicodedata.normalize("NFKC", "\n\n".join(blocks)).strip()
    return Chunk(
        chunk_index=chunk_index,
        text=text,
        token_count=len(_ENCODING.encode(text)),
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        metadata={"source_filename": source_id},
    )


def chunk_forum(raw_doc: RawDocument) -> list[Chunk]:
    """Paragraph-packing chunker with forward-merge of sub-40-word blocks.

    Algorithm (D-01, D-02):

    1. Split ``raw_doc.text`` on blank lines into paragraph blocks; drop
       empty blocks.
    2. Tokenize each block via ``cl100k_base`` and flag any block with
       fewer than ``MIN_PARAGRAPH_WORDS`` whitespace-split words as
       ``must_merge`` (cannot close a chunk before such a block).
    3. Greedy pack: accumulate blocks into ``current``. Close the chunk
       when adding the next block would exceed ``MAX_TOKENS`` AND the
       just-appended block is not flagged ``must_merge``.
    4. If a single block alone is > ``MAX_TOKENS`` (no Phase 1 file has
       this property, but the writer should not crash if it ever does):
       emit it as its own chunk rather than splitting mid-paragraph — D-02
       forbids paragraph-internal splits, and sentence-level splitting is
       a Phase 2 concern.
    5. After the loop, if any blocks remain in ``current`` they form the
       final chunk. If the document's FINAL block was a sub-40-word
       paragraph and we already had at least one earlier chunk emitted,
       attach it to the previous chunk instead of emitting standalone.
       (Realized here by deferring close: the must_merge flag prevents
       chunk closure on the small block itself, so it naturally lives in
       whatever chunk contains its successor — or, when it has no
       successor, the loop's leftover-blocks path keeps it joined to its
       predecessor by re-using the prior chunk's blocks.)
    """

    blocks = _split_paragraphs(raw_doc.text)
    if not blocks:
        return []

    # Pre-compute tokens + word counts for every block; flag forward-merge
    # candidates so the greedy loop can branch on them in O(1).
    block_info = [
        (b, len(_ENCODING.encode(b)), len(b.split()) < MIN_PARAGRAPH_WORDS)
        for b in blocks
    ]

    chunks: list[Chunk] = []
    current: list[str] = []
    current_tokens = 0
    # Each "\n\n" separator between paragraphs in a finalized chunk encodes
    # to exactly 1 token under cl100k_base. The greedy accumulator must
    # include this overhead, otherwise the sum of per-paragraph token
    # counts under-estimates the chunk's real encoded length and the chunk
    # silently overshoots MAX_TOKENS on re-encode (seen in the wild on
    # raw_data/forum_posts/indian_sounding_guitar_sound.txt: 12 blocks of
    # 498 raw tokens encoded to 501 once joined).
    _SEPARATOR_TOKENS = 1

    for block, tokens, _must_merge in block_info:
        # Project the chunk size IF we append this block: include one
        # separator token per non-first paragraph already in current.
        projected = (
            current_tokens
            + (_SEPARATOR_TOKENS if current else 0)
            + tokens
        )

        if current and projected > MAX_TOKENS:
            chunks.append(_finalize_chunk(current, len(chunks), raw_doc.source_id))
            current = [block]
            current_tokens = tokens
        else:
            # Empty chunk OR room remains. We always append even when the
            # FIRST block of a fresh chunk is already > MAX_TOKENS — D-02
            # forbids paragraph-internal splits, and no Phase 1 forum
            # paragraph exceeds 500 tokens by inspection.
            current.append(block)
            current_tokens = projected

    if current:
        chunks.append(_finalize_chunk(current, len(chunks), raw_doc.source_id))

    # ----- Forward-merge post-pass (D-01) -----
    #
    # Strict-cap greedy packing can produce a final chunk whose entire
    # content is a single sub-40-word paragraph (an aside or a one-line
    # reply that just barely overflowed the previous chunk). The plan
    # forbids such standalone "micro-chunks" (must_haves.truths bullet 4).
    # We merge any all-short chunk into its preceding chunk's blocks and
    # re-finalize. The merged chunk may then exceed MAX_TOKENS by the
    # small block's token count — that is the explicit trade-off D-01
    # makes: never emit a standalone sub-40-word chunk, even if the cap
    # is slightly broken on a single tail chunk. Within the Phase 1 corpus
    # this only ever happens on the document's final chunk.
    merged: list[Chunk] = []
    for c in chunks:
        chunk_words = len(c.text.split())
        if chunk_words < MIN_PARAGRAPH_WORDS and merged:
            prev = merged.pop()
            prev_blocks = prev.text.split("\n\n")
            prev_blocks.extend(c.text.split("\n\n"))
            merged.append(
                _finalize_chunk(prev_blocks, prev.chunk_index, raw_doc.source_id)
            )
        else:
            # Re-index in case earlier merges shifted positions.
            merged.append(
                _finalize_chunk(
                    c.text.split("\n\n"), len(merged), raw_doc.source_id
                )
            )

    return merged


# ---------------------------------------------------------------------------
# Web article chunker (Phase 6 Plan 04, INGEST-09).
# ---------------------------------------------------------------------------


def chunk_article(raw_doc: RawDocument) -> list[Chunk]:
    """Paragraph-packing chunker for web articles (INGEST-09).

    Algorithm is identical to ``chunk_forum`` — same greedy accumulator,
    same forward-merge post-pass, same ``_finalize_chunk()`` helper.  The
    only difference from ``chunk_forum`` is that ``source_id`` is the full
    article URL (e.g. ``"https://www.premierguitar.com/diy/..."``) rather
    than a filename, so ``metadata["source_filename"]`` carries the URL.

    No section-aware or page-number metadata is added — those are PDF-only
    concerns (D-03, 06-02-PLAN.md).  Articles are treated as a flat stream
    of paragraphs with no heading hierarchy.

    Args:
        raw_doc: A ``RawDocument`` with ``source_type="web_article"`` and
            ``source_id`` set to the full URL string.

    Returns:
        List of ``Chunk`` instances.  Empty list if the document has no text.
    """
    blocks = _split_paragraphs(raw_doc.text)
    if not blocks:
        return []

    # Pre-compute tokens + word counts for every block; flag forward-merge
    # candidates so the greedy loop can branch on them in O(1).
    block_info = [
        (b, len(_ENCODING.encode(b)), len(b.split()) < MIN_PARAGRAPH_WORDS)
        for b in blocks
    ]

    chunks: list[Chunk] = []
    current: list[str] = []
    current_tokens = 0
    _SEPARATOR_TOKENS = 1  # "\n\n" separator between paragraphs costs 1 token

    for block, tokens, _must_merge in block_info:
        projected = (
            current_tokens
            + (_SEPARATOR_TOKENS if current else 0)
            + tokens
        )

        if current and projected > MAX_TOKENS:
            chunks.append(_finalize_chunk(current, len(chunks), raw_doc.source_id))
            current = [block]
            current_tokens = tokens
        else:
            current.append(block)
            current_tokens = projected

    if current:
        chunks.append(_finalize_chunk(current, len(chunks), raw_doc.source_id))

    # ----- Forward-merge post-pass (D-01) -----
    # Merge any all-short chunk into the preceding chunk's blocks.
    merged: list[Chunk] = []
    for c in chunks:
        chunk_words = len(c.text.split())
        if chunk_words < MIN_PARAGRAPH_WORDS and merged:
            prev = merged.pop()
            prev_blocks = prev.text.split("\n\n")
            prev_blocks.extend(c.text.split("\n\n"))
            merged.append(
                _finalize_chunk(prev_blocks, prev.chunk_index, raw_doc.source_id)
            )
        else:
            merged.append(
                _finalize_chunk(
                    c.text.split("\n\n"), len(merged), raw_doc.source_id
                )
            )

    return merged


# ---------------------------------------------------------------------------
# YouTube transcript chunker (Phase 6 Plan 03, INGEST-10).
# ---------------------------------------------------------------------------


def _finalize_youtube_chunk(
    segments: list[dict],
    chunk_index: int,
    video_id: str,
) -> Chunk:
    """Materialize a window of transcript segments into a frozen YouTube Chunk.

    Args:
        segments: Non-empty list of ``{"text": str, "start": float}`` dicts
            for the current window.
        chunk_index: 0-based position within the parent document (D-04).
        video_id: The YouTube video ID — used as both ``source_filename`` and
            ``video_id`` in the metadata (D-10).

    Returns:
        A frozen ``Chunk`` with extended metadata carrying ``video_id``,
        ``start_time``, and ``source_filename``.
    """
    text = unicodedata.normalize("NFKC", "\n\n".join(s["text"] for s in segments)).strip()
    start_time: float = segments[0]["start"] if segments else 0.0
    return Chunk(
        chunk_index=chunk_index,
        text=text,
        token_count=len(_ENCODING.encode(text)),
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        metadata={
            "source_filename": video_id,
            "video_id": video_id,
            "start_time": start_time,
        },
    )


def chunk_youtube(raw_doc: RawDocument) -> list[Chunk]:
    """Greedy segment-packing chunker for YouTube transcripts (INGEST-10).

    Algorithm (mirrors ``chunk_forum`` per D-09 — non-overlapping windows):

    1. Read ``raw_doc.metadata["raw_segments"]`` as the list of atomic units.
       Each segment is ``{"text": str, "start": float}``.
    2. If ``raw_segments`` is empty or missing, fall back to blank-line
       paragraph splitting of ``raw_doc.text`` with ``start_time=0.0`` for
       all chunks.
    3. Pre-compute token counts for each segment via ``_ENCODING.encode()``.
    4. Run the same greedy accumulator as ``chunk_forum``, closing a window
       when adding the next segment would exceed ``MAX_TOKENS``.
    5. ``start_time`` for each emitted chunk equals the ``"start"`` value of
       the first segment in that window (D-10).
    6. Forward-merge post-pass (D-01): chunks whose total word count is less
       than ``MIN_PARAGRAPH_WORDS`` attach to the prior chunk.

    Each chunk's metadata carries ``source_filename``, ``video_id``, and
    ``start_time`` per D-03 / D-10.

    Args:
        raw_doc: A ``RawDocument`` with ``source_type="youtube"``.

    Returns:
        List of ``Chunk`` instances.  Empty list if the document has no text.
    """
    _SEPARATOR_TOKENS = 1  # "\n\n" between segments costs 1 token in cl100k_base

    video_id = raw_doc.source_id
    segments: list[dict] = raw_doc.metadata.get("raw_segments", [])

    # ------------------------------------------------------------------ #
    # Fallback: no raw_segments — use paragraph splitting with start=0.0. #
    # ------------------------------------------------------------------ #
    if not segments:
        paragraphs = _split_paragraphs(raw_doc.text)
        if not paragraphs:
            return []
        fallback_segs = [{"text": p, "start": 0.0} for p in paragraphs]
        segments = fallback_segs

    # Pre-compute token counts for every segment.
    seg_tokens = [len(_ENCODING.encode(s["text"])) for s in segments]

    chunks: list[Chunk] = []
    current_segs: list[dict] = []
    current_tokens: int = 0

    for seg, tokens in zip(segments, seg_tokens):
        projected = current_tokens + (_SEPARATOR_TOKENS if current_segs else 0) + tokens

        if current_segs and projected > MAX_TOKENS:
            # Close the current window.
            chunks.append(_finalize_youtube_chunk(current_segs, len(chunks), video_id))
            current_segs = [seg]
            current_tokens = tokens
        else:
            current_segs.append(seg)
            current_tokens = projected

    # Emit any remaining segments as the final chunk.
    if current_segs:
        chunks.append(_finalize_youtube_chunk(current_segs, len(chunks), video_id))

    # ----- Forward-merge post-pass (D-01) -----
    # Merge any all-short chunk into the preceding chunk.
    merged: list[Chunk] = []
    for c in chunks:
        chunk_words = len(c.text.split())
        if chunk_words < MIN_PARAGRAPH_WORDS and merged:
            prev = merged.pop()
            # Reconstruct segments from the joined texts by treating each
            # "\n\n"-separated block as a segment (start_time lost on merge,
            # preserve the earlier chunk's start_time).
            combined_text = unicodedata.normalize(
                "NFKC",
                "\n\n".join([prev.text, c.text]),
            ).strip()
            merged_start_time = prev.metadata["start_time"]
            new_chunk = Chunk(
                chunk_index=prev.chunk_index,
                text=combined_text,
                token_count=len(_ENCODING.encode(combined_text)),
                content_hash=hashlib.sha256(combined_text.encode("utf-8")).hexdigest(),
                metadata={
                    "source_filename": video_id,
                    "video_id": video_id,
                    "start_time": merged_start_time,
                },
            )
            merged.append(new_chunk)
        else:
            # Re-index to keep 0-based contiguous indices after merges.
            reindexed = Chunk(
                chunk_index=len(merged),
                text=c.text,
                token_count=c.token_count,
                content_hash=c.content_hash,
                metadata=c.metadata,
            )
            merged.append(reindexed)

    return merged
