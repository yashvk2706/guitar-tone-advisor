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
    # NOTE: "pdf_manual" is now implemented (Phase 6). Use a truly unknown type.
    bad = RawDocument(
        source_type="totally_unknown_type",
        source_id="unknown.xyz",
        title=None,
        text="anything",
        content_hash="x",
    )
    with pytest.raises(NotImplementedError) as exc:
        chunk_document(bad)
    assert "totally_unknown_type" in str(exc.value)


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


# ---------------------------------------------------------------------------
# PDF chunker tests (Phase 6 Plan 02).
# ---------------------------------------------------------------------------

from unittest.mock import patch  # noqa: E402

from app.ingest.chunker import chunk_pdf  # noqa: E402


def _make_pdf_doc(
    source_id: str = "/fake/path/manual.pdf",
    text: str = "Some text",
) -> RawDocument:
    """Build a synthetic pdf_manual RawDocument inline."""
    return RawDocument(
        source_type="pdf_manual",
        source_id=source_id,
        title="manual",
        text=text,
        content_hash="dummy-hash",
    )


def _page_dict(page_num: int, text: str) -> dict:
    """Build a minimal pymupdf4llm page dict."""
    return {
        "metadata": {"page": page_num},
        "text": text,
    }


def _make_two_call_pages(
    *body_pages_list: list,
) -> list:
    """Return side_effect list for the two pymupdf4llm.to_markdown calls.

    chunk_pdf() calls to_markdown twice:
      1. Without pages= filter → to count total pages (determines cover skip).
      2. With pages=list(range(1, n_pages)) → returns pages starting at index 1.

    To simulate this, the first call returns cover + body; the second returns
    only the body pages (indices 1..n-1).
    """
    cover = _page_dict(1, "Cover Page")
    # Build the full list (cover + body pages).
    all_pages = [cover] + list(body_pages_list)
    # The second call with pages=[1,2,...] returns body pages only.
    body_only = list(body_pages_list)
    return [all_pages, body_only]


def test_pdf_chunker_dispatch() -> None:
    """chunk_document() routes 'pdf_manual' to chunk_pdf() without raising NotImplementedError."""
    page_text = "## Controls\n\n" + " ".join(["word"] * 50) + ".\n"
    body_page = _page_dict(2, page_text)

    with patch("pymupdf4llm.to_markdown") as mock_to_markdown:
        mock_to_markdown.side_effect = _make_two_call_pages(body_page)
        doc = _make_pdf_doc()
        # Must not raise NotImplementedError
        chunks = chunk_document(doc)
    assert isinstance(chunks, list)


def test_pdf_chunker_no_table_split() -> None:
    """Tables (GFM | lines) are never split across chunk boundaries."""
    # Build a large table that would force a split in a naive chunker.
    header = "| Column A | Column B | Column C |\n|---|---|---|\n"
    rows = "".join(f"| Data {i} | Data {i} | Data {i} |\n" for i in range(30))
    table_block = header + rows

    # Pad with text before the table to fill the greedy accumulator.
    pre_text = " ".join(["word"] * 400)
    page_text = pre_text + "\n\n" + table_block

    body_page = _page_dict(2, page_text)

    with patch("pymupdf4llm.to_markdown") as mock_to_markdown:
        mock_to_markdown.side_effect = _make_two_call_pages(body_page)
        doc = _make_pdf_doc()
        chunks = chunk_pdf(doc)

    # Verify no chunk contains a partial table (starts with | but the table header
    # is in a different chunk). We check that any chunk containing | lines also
    # contains the header row pattern.
    table_lines_found = False
    for chunk in chunks:
        lines = chunk.text.splitlines()
        has_pipe_lines = any(line.lstrip().startswith("|") for line in lines)
        if has_pipe_lines:
            table_lines_found = True
            # Check that the first | line in this chunk is the header (not a data row
            # orphaned from its header). The table is atomic: if any | line is present,
            # the header "Column A" must be present too.
            assert "Column A" in chunk.text, (
                f"Table split detected: chunk contains | lines but no header:\n{chunk.text[:300]}"
            )
    assert table_lines_found, "Expected table lines in at least one chunk"


def test_pdf_chunker_skips_cover() -> None:
    """Cover page (page index 0, page_num=1) is skipped; no cover text in any chunk."""
    cover_text = "User Manual Cover Page\nModel Number XYZ-9000\n"
    body_text = "## Introduction\n\n" + " ".join(["word"] * 100) + ".\n"

    body_page = _page_dict(2, body_text)

    with patch("pymupdf4llm.to_markdown") as mock_to_markdown:
        # First call returns cover + body (to count pages);
        # second call (with pages=[1]) returns only the body page.
        mock_to_markdown.side_effect = [
            [_page_dict(1, cover_text), body_page],
            [body_page],
        ]
        doc = _make_pdf_doc()
        chunks = chunk_pdf(doc)

    for chunk in chunks:
        assert "User Manual Cover Page" not in chunk.text, (
            f"Cover page text found in chunk: {chunk.text[:200]}"
        )


def test_pdf_chunk_metadata() -> None:
    """Every chunk produced by chunk_pdf() has 'section_heading' and 'page_number' keys."""
    page_text = "## Specifications\n\n" + " ".join(["word"] * 60) + ".\n"
    body_page = _page_dict(2, page_text)

    with patch("pymupdf4llm.to_markdown") as mock_to_markdown:
        mock_to_markdown.side_effect = _make_two_call_pages(body_page)
        doc = _make_pdf_doc()
        chunks = chunk_pdf(doc)

    assert len(chunks) > 0, "Expected at least one chunk"
    for chunk in chunks:
        assert "section_heading" in chunk.metadata, (
            f"Missing 'section_heading' in chunk metadata: {chunk.metadata}"
        )
        assert "page_number" in chunk.metadata, (
            f"Missing 'page_number' in chunk metadata: {chunk.metadata}"
        )
        assert isinstance(chunk.metadata["section_heading"], str)
        assert isinstance(chunk.metadata["page_number"], int)


def test_pdf_chunks_within_token_budget() -> None:
    """All chunks produced by chunk_pdf() have token_count <= MAX_TOKENS."""
    # Build a multi-page document with paragraphs
    paragraphs = [" ".join(["word"] * 200) for _ in range(5)]
    page_text = "\n\n".join(paragraphs)
    body_page1 = _page_dict(2, page_text)
    body_page2 = _page_dict(3, page_text)

    with patch("pymupdf4llm.to_markdown") as mock_to_markdown:
        mock_to_markdown.side_effect = _make_two_call_pages(body_page1, body_page2)
        doc = _make_pdf_doc()
        chunks = chunk_pdf(doc)

    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.token_count <= MAX_TOKENS, (
            f"Chunk exceeds MAX_TOKENS ({MAX_TOKENS}): token_count={chunk.token_count}"
        )


# ---------------------------------------------------------------------------
# YouTube chunker tests (Phase 6 Plan 03).
# ---------------------------------------------------------------------------

from app.ingest.chunker import chunk_youtube  # noqa: E402


def _make_youtube_doc(
    source_id: str = "testID123ab",
    raw_segments: list | None = None,
) -> RawDocument:
    """Build a synthetic YouTube RawDocument."""
    if raw_segments is None:
        raw_segments = [
            {"text": "word " * 50, "start": 0.0},
            {"text": "word " * 50, "start": 10.5},
        ]
    full_text = " ".join(s["text"] for s in raw_segments)
    import hashlib
    content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    return RawDocument(
        source_type="youtube",
        source_id=source_id,
        title=None,
        text=full_text,
        content_hash=content_hash,
        metadata={"raw_segments": raw_segments},
    )


def test_youtube_chunk_metadata() -> None:
    """All chunks from chunk_youtube() carry video_id, start_time, source_filename."""
    doc = _make_youtube_doc()
    chunks = chunk_youtube(doc)
    assert len(chunks) > 0, "Expected at least one chunk"
    for chunk in chunks:
        assert "video_id" in chunk.metadata, (
            f"Missing 'video_id' in chunk metadata: {chunk.metadata}"
        )
        assert "start_time" in chunk.metadata, (
            f"Missing 'start_time' in chunk metadata: {chunk.metadata}"
        )
        assert "source_filename" in chunk.metadata, (
            f"Missing 'source_filename' in chunk metadata: {chunk.metadata}"
        )
        assert chunk.metadata["video_id"] == "testID123ab"
        assert chunk.metadata["source_filename"] == "testID123ab"


def test_youtube_chunk_start_time() -> None:
    """First window start_time == segments[0]['start']; second window == first snippet's start."""
    # Build enough segments to force at least 2 windows (each ~300 tokens per window).
    seg_text = "token " * 60  # ~60 tokens per segment
    # 6 segments of ~60 tokens each -> ~360 tokens per window (2 windows if split at ~300)
    raw_segments = [
        {"text": seg_text, "start": float(i * 5)} for i in range(10)
    ]
    doc = _make_youtube_doc(source_id="timeTestID1", raw_segments=raw_segments)
    chunks = chunk_youtube(doc)
    assert len(chunks) >= 2, (
        f"Expected at least 2 chunks for 10 segments of ~60 tokens, got {len(chunks)}"
    )
    # First chunk: start_time == first segment's start (0.0).
    assert chunks[0].metadata["start_time"] == 0.0, (
        f"First chunk start_time should be 0.0, got {chunks[0].metadata['start_time']}"
    )
    # Second chunk: start_time == start of the first segment in that window (> 0.0).
    assert chunks[1].metadata["start_time"] > 0.0, (
        f"Second chunk start_time should be > 0.0, got {chunks[1].metadata['start_time']}"
    )


def test_youtube_source_type_dispatch() -> None:
    """chunk_document() routes source_type='youtube' without raising NotImplementedError."""
    doc = _make_youtube_doc()
    # Must not raise NotImplementedError
    chunks = chunk_document(doc)
    assert isinstance(chunks, list)
    assert len(chunks) > 0


def test_youtube_chunks_within_token_budget() -> None:
    """All chunks produced by chunk_youtube() have token_count <= MAX_TOKENS."""
    # Large number of segments to force multiple windows.
    seg_text = "word " * 100  # ~100 tokens
    raw_segments = [{"text": seg_text, "start": float(i * 3)} for i in range(20)]
    doc = _make_youtube_doc(source_id="budgetTestID", raw_segments=raw_segments)
    chunks = chunk_youtube(doc)
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.token_count <= MAX_TOKENS, (
            f"Chunk exceeds MAX_TOKENS ({MAX_TOKENS}): token_count={chunk.token_count}"
        )


def test_youtube_source_type_is_correct_string() -> None:
    """The string 'youtube_transcript' must not appear anywhere in chunker.py."""
    chunker_path = (
        Path(__file__).resolve().parent.parent / "app" / "ingest" / "chunker.py"
    )
    contents = chunker_path.read_text(encoding="utf-8")
    assert "youtube_transcript" not in contents, (
        "Found forbidden string 'youtube_transcript' in chunker.py — "
        "source_type must be 'youtube' to satisfy the DB CHECK constraint"
    )
