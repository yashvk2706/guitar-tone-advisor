"""Phase 1 Plan 02 Task 2 — chunker unit tests.

Pins the 9 behaviors from
``.planning/phases/01-schema-forum-ingestion-golden-eval-set/01-02-PLAN.md``
``Task 2 <behavior>``:

  1. ``chunk_document`` raises ``NotImplementedError`` for non-forum sources
     (CLAUDE.md hard constraint: chunking dispatches on source_type).
  2. Short documents yield exactly one chunk (no padding to a floor).
  3. Long documents yield multiple chunks, all ≤ 500 tokens.
  4. No chunk in the real corpus exceeds 500 tokens (hard cap).
  5. Paragraphs < 40 words are merged forward — never appear standalone.
  6. ``chunk_index`` is 0-based and resets per document.
  7. Every chunk carries ``metadata["source_filename"]`` (D-03).
  8. Chunking the same RawDocument twice produces byte-identical hashes.
  9. The real 10-file corpus produces 10–50 chunks; every chunk has a
     positive token count and a known source filename.

Run with::

    pytest tests/test_chunker.py -x -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
import tiktoken

from app.ingest.chunker import (
    MAX_TOKENS,
    MIN_PARAGRAPH_WORDS,
    Chunk,
    chunk_document,
    chunk_forum,
)
from app.ingest.loader import RawDocument, load_forum_posts

REAL_CORPUS = Path(__file__).resolve().parent.parent / "raw_data" / "forum_posts"
_ENC = tiktoken.get_encoding("cl100k_base")


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _make_doc(text: str, source_id: str = "synthetic.txt") -> RawDocument:
    """Build a synthetic forum RawDocument inline (no I/O)."""

    return RawDocument(
        source_type="forum",
        source_id=source_id,
        title=None,
        text=text,
        content_hash="dummy-hash-not-asserted-here",
    )


def _paragraph_of_tokens(target_tokens: int, marker: str = "alpha") -> str:
    """Build a paragraph whose token count under cl100k_base is approximately
    ``target_tokens``. Uses a repeated short word so token count is predictable
    (most common tokens map ~1 token each).
    """

    # `marker` is one token for short ASCII words; pad with a sentence-end so
    # the paragraph reads like prose rather than a flat token stream.
    body = (marker + " ") * target_tokens
    paragraph = body.strip() + "."
    return paragraph


# ---------------------------------------------------------------------------
# Behavior tests.
# ---------------------------------------------------------------------------


def test_dispatch_raises_for_unknown_source_type() -> None:
    bad = RawDocument(
        source_type="pdf_manual",
        source_id="marshall_jcm800.pdf",
        title=None,
        text="anything",
        content_hash="x",
    )
    with pytest.raises(NotImplementedError) as exc:
        chunk_document(bad)
    assert "pdf_manual" in str(exc.value)


def test_short_document_yields_one_chunk() -> None:
    text = _paragraph_of_tokens(200)
    doc = _make_doc(text)
    chunks = chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].token_count <= MAX_TOKENS
    assert chunks[0].metadata["source_filename"] == "synthetic.txt"


def test_long_document_yields_multiple_chunks() -> None:
    # 3 paragraphs of ~400 tokens each -> ~1200 tokens total -> must split.
    paragraphs = [
        _paragraph_of_tokens(400, "alpha"),
        _paragraph_of_tokens(400, "beta"),
        _paragraph_of_tokens(400, "gamma"),
    ]
    doc = _make_doc("\n\n".join(paragraphs))
    chunks = chunk_document(doc)
    assert len(chunks) >= 2
    assert all(c.token_count <= MAX_TOKENS for c in chunks)
    # chunk_index is contiguous 0..n-1
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_no_chunk_exceeds_500_tokens() -> None:
    """Hard cap honored across all 10 real corpus files."""

    docs = load_forum_posts(REAL_CORPUS)
    for doc in docs:
        for c in chunk_document(doc):
            assert c.token_count <= MAX_TOKENS, (
                f"{doc.source_id} chunk {c.chunk_index} has {c.token_count} tokens"
            )


def test_short_paragraph_merged_forward() -> None:
    """A < 40-word paragraph between two large paragraphs is folded into the
    chunk containing its neighbor — never appears standalone.
    """

    p1 = _paragraph_of_tokens(350, "p1word")  # large -> closes a chunk
    p2_short = "A very brief aside containing only a few words."  # ~10 words
    p3 = _paragraph_of_tokens(200, "p3word")
    doc = _make_doc(f"{p1}\n\n{p2_short}\n\n{p3}")
    chunks = chunk_document(doc)

    # The short paragraph's text must live inside SOME chunk.
    assert any(p2_short in c.text for c in chunks)
    # And no chunk should be just the short paragraph in isolation.
    for c in chunks:
        assert c.text.strip() != p2_short.strip(), (
            "<40-word paragraph emitted as standalone chunk; forward-merge failed"
        )


def test_trailing_short_paragraph_attaches_to_previous_chunk() -> None:
    """If a sub-40-word paragraph is the FINAL paragraph in the document, it
    must attach to the previous chunk rather than emit standalone.
    """

    p1 = _paragraph_of_tokens(350, "leadword")
    trailing_short = "Just a final note."  # ~4 words
    doc = _make_doc(f"{p1}\n\n{trailing_short}")
    chunks = chunk_document(doc)
    assert any(trailing_short in c.text for c in chunks)
    for c in chunks:
        assert c.text.strip() != trailing_short.strip()


def test_chunk_index_resets_per_document() -> None:
    doc_a = _make_doc(_paragraph_of_tokens(150), source_id="a.txt")
    doc_b = _make_doc(_paragraph_of_tokens(150), source_id="b.txt")
    chunks_a = chunk_document(doc_a)
    chunks_b = chunk_document(doc_b)
    assert chunks_a[0].chunk_index == 0
    assert chunks_b[0].chunk_index == 0


def test_metadata_contains_source_filename() -> None:
    docs = load_forum_posts(REAL_CORPUS)
    for doc in docs:
        for c in chunk_document(doc):
            assert "source_filename" in c.metadata
            assert c.metadata["source_filename"] == doc.source_id


def test_chunking_is_deterministic() -> None:
    docs = load_forum_posts(REAL_CORPUS)
    first = [
        (c.chunk_index, c.content_hash)
        for d in docs
        for c in chunk_document(d)
    ]
    second = [
        (c.chunk_index, c.content_hash)
        for d in docs
        for c in chunk_document(d)
    ]
    assert first == second


def test_real_corpus_chunks() -> None:
    docs = load_forum_posts(REAL_CORPUS)
    chunks = [c for d in docs for c in chunk_document(d)]
    assert 10 <= len(chunks) <= 50, f"chunk count out of expected band: {len(chunks)}"
    expected_filenames = {d.source_id for d in docs}
    for c in chunks:
        assert c.token_count > 0
        assert c.metadata["source_filename"] in expected_filenames


# ---------------------------------------------------------------------------
# Supplementary contract tests.
# ---------------------------------------------------------------------------


def test_chunk_is_frozen() -> None:
    chunks = chunk_document(_make_doc(_paragraph_of_tokens(100)))
    with pytest.raises(Exception):
        chunks[0].text = "mutated"  # type: ignore[misc]


def test_empty_document_returns_no_chunks() -> None:
    """An empty / whitespace-only document yields zero chunks (not an error).
    Plan 04's writer records that as ``chunks_written=0``."""

    doc = _make_doc("   \n\n   \n\n")
    assert chunk_document(doc) == []


def test_chunk_forum_directly_matches_dispatch() -> None:
    """``chunk_forum`` and ``chunk_document`` produce identical output for a
    forum RawDocument."""

    doc = _make_doc(_paragraph_of_tokens(150))
    via_dispatch = chunk_document(doc)
    direct = chunk_forum(doc)
    assert [c.content_hash for c in via_dispatch] == [c.content_hash for c in direct]


def test_constants_are_correct_values() -> None:
    assert MAX_TOKENS == 500
    assert MIN_PARAGRAPH_WORDS == 40
