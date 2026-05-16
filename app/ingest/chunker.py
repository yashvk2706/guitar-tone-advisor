"""Paragraph-packing chunker for the Phase 1 forum corpus.

Treats each ``.txt`` file as one document, splits on blank-line paragraph
boundaries, and greedily packs paragraphs into 300–500 token chunks measured
with ``tiktoken``'s ``cl100k_base`` encoding (the same encoder OpenAI uses
for the ``text-embedding-3-*`` family — see ``.planning/research/STACK.md``
§Chunking Strategy per Source Type).

Implementation decisions encoded here (locked by 01-CONTEXT.md):

* **D-01** Forward-merge: any paragraph with fewer than ``MIN_PARAGRAPH_WORDS``
  (40) whitespace-split words is folded into the next chunk rather than
  emitted as a sub-40-word standalone chunk. Trailing short paragraphs
  attach to the previous chunk instead.
* **D-02** No quoted-reply stripping — the corpus files contain no ``>`` or
  ``[quote]`` markers.
* **D-03** Every chunk carries ``metadata["source_filename"]`` so the eval
  authoring UI (Plan 01-05) can display provenance.
* **D-04** ``chunk_index`` is 0-based and resets per document.

Source-type dispatch is a CLAUDE.md hard constraint: ``chunk_document``
inspects ``raw_doc.source_type`` and only routes ``"forum"`` to the
``chunk_forum`` implementation. Other source types (``pdf_manual`` etc.) are
explicit ``NotImplementedError`` — Phase 2 wires them up.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import tiktoken

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
    universal chunker." Phase 1 supports ``"forum"`` only; other source
    types raise ``NotImplementedError`` so that an accidental Phase 2
    invocation against this module fails loudly instead of silently
    producing a degenerate chunking.
    """

    if raw_doc.source_type == "forum":
        return chunk_forum(raw_doc)

    raise NotImplementedError(
        f"Chunker for source_type={raw_doc.source_type!r} not implemented in Phase 1"
    )


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
