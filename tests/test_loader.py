"""Phase 1 Plan 02 Task 1 — forum loader unit tests.

These tests pin the contract documented in
``.planning/phases/01-schema-forum-ingestion-golden-eval-set/01-02-PLAN.md``
``<task type="auto"> Task 1`` ``<behavior>``: deterministic NFKC normalization,
content hashing, ``.txt``-only filter, sorted output, and path-traversal
defense (T-02-01).

Run with::

    pytest tests/test_loader.py -x -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest.loader import RawDocument, load_forum_posts


REAL_CORPUS = Path(__file__).resolve().parent.parent / "raw_data" / "forum_posts"


# ---------------------------------------------------------------------------
# Tests against the real Phase 1 corpus (10 forum .txt files).
# ---------------------------------------------------------------------------


def test_loads_all_ten_files() -> None:
    docs = load_forum_posts(REAL_CORPUS)
    assert len(docs) == 10, f"expected 10 RawDocuments, got {len(docs)}"
    assert all(isinstance(d, RawDocument) for d in docs)


def test_source_id_is_filename() -> None:
    docs = load_forum_posts(REAL_CORPUS)
    ids = {d.source_id for d in docs}
    disk_names = {p.name for p in REAL_CORPUS.glob("*.txt")}
    assert ids == disk_names
    assert all(sid.endswith(".txt") for sid in ids)


def test_source_type_is_forum() -> None:
    docs = load_forum_posts(REAL_CORPUS)
    assert all(d.source_type == "forum" for d in docs)


def test_content_hash_is_deterministic() -> None:
    first = {d.source_id: d.content_hash for d in load_forum_posts(REAL_CORPUS)}
    second = {d.source_id: d.content_hash for d in load_forum_posts(REAL_CORPUS)}
    assert first == second
    # And it must be a sha256 hex string (64 lowercase hex chars).
    for h in first.values():
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# Tests against synthetic tmp_path fixtures.
# ---------------------------------------------------------------------------


def test_text_is_nfkc_normalized(tmp_path: Path) -> None:
    # U+FB01 LATIN SMALL LIGATURE FI -> "fi" after NFKC.
    (tmp_path / "ligature.txt").write_text("the ﬁnal answer", encoding="utf-8")
    docs = load_forum_posts(tmp_path)
    assert len(docs) == 1
    assert "fi" in docs[0].text  # decomposed
    assert "ﬁ" not in docs[0].text  # original ligature gone


def test_skips_non_txt(tmp_path: Path) -> None:
    (tmp_path / "post.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "notes.md").write_text("ignored", encoding="utf-8")
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")
    docs = load_forum_posts(tmp_path)
    assert len(docs) == 1
    assert docs[0].source_id == "post.txt"


def test_path_traversal_safe(tmp_path: Path) -> None:
    """Passing a path containing ``..`` resolves cleanly and never escapes."""

    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "inside.txt").write_text("inside corpus", encoding="utf-8")
    # File outside `sub` — load_forum_posts(sub/..) should never reach it
    # because we resolve() and then glob the resolved directory.
    (tmp_path / "outside.txt").write_text("outside corpus", encoding="utf-8")

    direct = load_forum_posts(sub)
    traversed = load_forum_posts(sub / ".." / "sub")  # round-trip via ..

    # Both calls see the same single file in `sub`, never `outside.txt`.
    assert {d.source_id for d in direct} == {"inside.txt"}
    assert {d.source_id for d in traversed} == {"inside.txt"}
    assert {d.content_hash for d in direct} == {d.content_hash for d in traversed}


def test_returns_empty_for_empty_directory(tmp_path: Path) -> None:
    docs = load_forum_posts(tmp_path)
    assert docs == []


def test_title_is_stem_titlecased(tmp_path: Path) -> None:
    (tmp_path / "bb_king_tone.txt").write_text("text", encoding="utf-8")
    docs = load_forum_posts(tmp_path)
    assert docs[0].title == "Bb King Tone"


def test_rawdocument_is_frozen() -> None:
    docs = load_forum_posts(REAL_CORPUS)
    with pytest.raises(Exception):
        # frozen dataclass disallows attribute assignment
        docs[0].text = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PDF manual loader tests (Phase 6 Plan 02).
# ---------------------------------------------------------------------------

import os  # noqa: E402 — needed for os.path.isabs in assertions

from app.ingest.loader import load_pdf_manuals  # noqa: E402

MANUALS_DIR = Path(__file__).resolve().parent.parent / "raw_data" / "manuals"


def test_load_pdf_manuals_source_type() -> None:
    docs = load_pdf_manuals(MANUALS_DIR)
    assert all(d.source_type == "pdf_manual" for d in docs), (
        "All PDF manuals must have source_type='pdf_manual'"
    )


def test_load_pdf_manuals_source_id_is_absolute_path() -> None:
    docs = load_pdf_manuals(MANUALS_DIR)
    for doc in docs:
        assert os.path.isabs(doc.source_id), (
            f"source_id must be an absolute path, got: {doc.source_id!r}"
        )
        assert doc.source_id.endswith(".pdf"), (
            f"source_id must end with '.pdf', got: {doc.source_id!r}"
        )


def test_load_pdf_manuals_count() -> None:
    docs = load_pdf_manuals(MANUALS_DIR)
    assert len(docs) == 15, f"Expected 15 PDF manuals, got {len(docs)}"


def test_load_pdf_manuals_content_hash_is_hex64() -> None:
    docs = load_pdf_manuals(MANUALS_DIR)
    for doc in docs:
        assert len(doc.content_hash) == 64, (
            f"content_hash must be 64 chars, got {len(doc.content_hash)} for {doc.source_id!r}"
        )
        assert all(c in "0123456789abcdef" for c in doc.content_hash), (
            f"content_hash must be lowercase hex, got: {doc.content_hash!r}"
        )


def test_load_pdf_manuals_sorted_order() -> None:
    first = load_pdf_manuals(MANUALS_DIR)
    second = load_pdf_manuals(MANUALS_DIR)
    assert [d.source_id for d in first] == [d.source_id for d in second], (
        "load_pdf_manuals must return documents in deterministic sorted order"
    )
