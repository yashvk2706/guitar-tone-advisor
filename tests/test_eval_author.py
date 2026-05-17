"""Unit tests for ``app.eval.author`` — the interactive authoring CLI.

The tests are split into two tiers:

* **Pure-Python helpers (tests 1, 3, 4, 5, 6).** Run unconditionally.
  Cover ``read_queries``, ``parse_accept_input``, ``parse_themes``,
  ``write_held_out_md``, and the no-direct-``openai``-import grep gate.
* **DB-touching helper (test 2) + end-to-end main (test 7).** Gated to
  ``pytest.skip`` when Postgres is unreachable (matches the convention
  in ``tests/test_pipeline.py``). Test 2 hand-inserts deterministic
  rows into ``documents`` / ``chunks`` so it does not require an
  embedding API key. Test 7 monkeypatches ``input()`` and the embedder
  factory so the interactive loop runs deterministically.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import uuid
from pathlib import Path

import pytest

from app.eval.schema import VALID_THEMES, GoldenTuple, load_golden_set


# ---------------------------------------------------------------------------
# Test 1: read_queries skips comments + blanks.
# ---------------------------------------------------------------------------


def test_reads_queries_file(tmp_path):
    from app.eval.author import read_queries

    qfile = tmp_path / "queries.md"
    qfile.write_text(
        "# === Topic: BB King ===\n"
        "\n"
        "What amp settings does BB King prefer?\n"
        "# inline comment, skip me\n"
        "Best overdrive for John Mayer blues?\n"
        "\n"
        "Funk neck-vs-bridge pickup question?\n",
        encoding="utf-8",
    )

    queries = read_queries(qfile)
    assert queries == [
        "What amp settings does BB King prefer?",
        "Best overdrive for John Mayer blues?",
        "Funk neck-vs-bridge pickup question?",
    ]


# ---------------------------------------------------------------------------
# Test 3: parse_accept_input 1-based indices, "skip", empty, range check.
# ---------------------------------------------------------------------------


def test_parse_accept_input():
    from app.eval.author import parse_accept_input

    assert parse_accept_input("1,3,4", 8) == [0, 2, 3]
    assert parse_accept_input("skip", 8) is None
    assert parse_accept_input("SKIP", 8) is None  # case-insensitive
    assert parse_accept_input("  skip ", 8) is None  # whitespace tolerant
    assert parse_accept_input("", 8) == []
    assert parse_accept_input("   ", 8) == []

    with pytest.raises(ValueError):
        parse_accept_input("9", 8)  # out of range (only 1..8 valid)
    with pytest.raises(ValueError):
        parse_accept_input("0", 8)  # 0 is not a valid 1-based index
    with pytest.raises(ValueError):
        parse_accept_input("abc", 8)  # non-integer
    with pytest.raises(ValueError):
        parse_accept_input("-1", 8)  # negative


# ---------------------------------------------------------------------------
# Test 4: parse_themes validates against the closed enum.
# ---------------------------------------------------------------------------


def test_parse_themes_validates_enum():
    from app.eval.author import parse_themes

    assert parse_themes("amp_settings, pedal_choice") == [
        "amp_settings",
        "pedal_choice",
    ]
    # Single theme still returns a list.
    assert parse_themes("signal_chain") == ["signal_chain"]
    # Extra whitespace inside is tolerated.
    assert parse_themes("  amp_settings  ,  pickup_tone  ") == [
        "amp_settings",
        "pickup_tone",
    ]

    with pytest.raises(ValueError) as exc:
        parse_themes("whammy_bar")
    assert "whammy_bar" in str(exc.value)

    # Empty / whitespace-only input is rejected (themes are required).
    with pytest.raises(ValueError):
        parse_themes("")
    with pytest.raises(ValueError):
        parse_themes("   ")


# ---------------------------------------------------------------------------
# Test 5: write_held_out_md emits the no-tuning statement + ISO timestamp.
# ---------------------------------------------------------------------------


def test_write_held_out_manifest(tmp_path):
    from app.eval.author import write_held_out_md

    _u = lambda n: str(uuid.UUID(int=n))  # noqa: E731
    tuples = [
        GoldenTuple(
            query="q0",
            expected_chunk_ids=[_u(0)],
            expected_themes=["amp_settings"],
            held_out=False,
        ),
        GoldenTuple(
            query="q1",
            expected_chunk_ids=[_u(1)],
            expected_themes=["pedal_choice"],
            held_out=True,
        ),
        GoldenTuple(
            query="q2",
            expected_chunk_ids=[_u(2)],
            expected_themes=["pickup_tone"],
            held_out=False,
        ),
        GoldenTuple(
            query="q3",
            expected_chunk_ids=[_u(3)],
            expected_themes=["signal_chain"],
            held_out=True,
        ),
    ]
    held_out_sources = ["bb_king_tone.txt", "funk_tone.txt"]

    out_path = tmp_path / "HELD_OUT.md"
    write_held_out_md(out_path, tuples, held_out_sources)

    body = out_path.read_text(encoding="utf-8")
    # Literal phrase, case-insensitive match.
    assert re.search(
        r"no retrieval tuning has been performed", body, re.IGNORECASE
    ), body
    # The two held-out indices show up as 1 and 3.
    assert "1" in body and "3" in body
    # ISO-8601 UTC timestamp on the Locked-at line.
    locked_at_line = [
        ln for ln in body.splitlines() if "Locked at" in ln or "locked at" in ln
    ]
    assert locked_at_line, "Locked-at line must be present"
    # Pull the timestamp; must be parseable as ISO-8601 ending in +00:00 or Z.
    m = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z))", body)
    assert m, f"ISO-8601 UTC timestamp missing from manifest: {body}"
    # Held-out source files are listed.
    for src in held_out_sources:
        assert src in body


# ---------------------------------------------------------------------------
# Test 6: author.py never imports openai directly (CLAUDE.md hard constraint).
# ---------------------------------------------------------------------------


def test_no_direct_openai_import():
    src = Path(__file__).resolve().parent.parent / "app" / "eval" / "author.py"
    assert src.exists()
    contents = src.read_text(encoding="utf-8")
    bad = re.compile(r"^\s*(from openai\b|import openai\b)", re.MULTILINE)
    matches = bad.findall(contents)
    assert matches == [], (
        f"app/eval/author.py must not import openai directly; found: {matches}"
    )
    # Positive signal: the factory is used.
    assert "get_embedder" in contents


# ---------------------------------------------------------------------------
# Helpers and fixtures for the DB-touching tests.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_conn():
    """Live Postgres connection. Skip the test if unreachable."""
    try:
        from app.db import get_conn, init_schema
    except Exception as e:  # pragma: no cover
        pytest.skip(f"app.db import failed: {e!r}")

    try:
        conn = get_conn()
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Postgres not reachable: {e!r}")

    try:
        init_schema(conn)
    except Exception as e:  # pragma: no cover
        conn.close()
        pytest.skip(f"init_schema failed: {e!r}")

    yield conn
    conn.close()


@pytest.fixture
def _seeded_corpus(db_conn):
    """Insert 10 deterministic rows into ``documents`` + ``chunks``.

    Each chunk has a unique ``(document_id, chunk_index)`` and a fake
    vector ``[0.001 * (i + j) for j in range(1536)]`` for chunk ``i``.
    Truncates both tables at teardown so the suite is hermetic.
    """
    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE chunks, documents CASCADE")
    db_conn.commit()

    doc_id_by_source: dict[str, str] = {}
    chunk_ids_by_index: dict[int, str] = {}
    sources = [f"seed_{i}.txt" for i in range(10)]
    with db_conn.cursor() as cur:
        for i, src in enumerate(sources):
            cur.execute(
                """
                INSERT INTO documents (source_type, source_id, title, content_hash)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                ("forum", src, f"Seed {i}", f"hash_{i}"),
            )
            doc_id = str(cur.fetchone()[0])
            doc_id_by_source[src] = doc_id

            vec = [0.001 * (i + j) for j in range(1536)]
            cur.execute(
                """
                INSERT INTO chunks (
                    document_id, source_type, chunk_index, chunk_text,
                    content_hash, token_count, embedding_model, embedding,
                    metadata_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    doc_id,
                    "forum",
                    0,
                    f"Seed chunk text {i} — words a b c d e f g h i j k l m n o p q r",
                    f"chash_{i}",
                    20,
                    "text-embedding-3-small",
                    vec,
                    json.dumps({"source_filename": src}),
                ),
            )
            chunk_ids_by_index[i] = str(cur.fetchone()[0])
    db_conn.commit()

    yield {
        "sources": sources,
        "doc_ids": doc_id_by_source,
        "chunk_ids": chunk_ids_by_index,
    }

    with db_conn.cursor() as cur:
        cur.execute("TRUNCATE chunks, documents CASCADE")
    db_conn.commit()


class _StubEmbedder:
    """Test double satisfying the Embedder Protocol shape."""

    model = "text-embedding-3-small"
    dim = 1536
    provider = "openai"

    def embed_query(self, text: str) -> list[float]:
        # Returns a fixed direction; deterministic across runs.
        return [0.001 * j for j in range(1536)]

    def embed_documents(self, texts):  # pragma: no cover (not used here)
        from app.embeddings.base import EmbeddingResult

        return EmbeddingResult(
            vectors=[[0.001 * j for j in range(1536)] for _ in texts],
            model=self.model,
            dim=self.dim,
            provider=self.provider,
        )


# ---------------------------------------------------------------------------
# Test 2: retrieve_candidates pulls k rows with the expected dict shape.
# ---------------------------------------------------------------------------


def test_retrieve_candidates_returns_top_k(db_conn, _seeded_corpus):
    from app.eval.author import retrieve_candidates

    cands = retrieve_candidates(db_conn, _StubEmbedder(), "test query", k=8)
    assert len(cands) == 8
    for c in cands:
        assert set(c.keys()) >= {"chunk_id", "chunk_text", "source_filename"}
        # chunk_id must be a UUID string.
        uuid.UUID(c["chunk_id"])
        # source_filename must be one of the seeded sources.
        assert c["source_filename"] in _seeded_corpus["sources"]


# ---------------------------------------------------------------------------
# Test 7: main() drives the loop end-to-end against the seeded corpus.
# ---------------------------------------------------------------------------


class _FakeInput:
    """Pop predetermined strings off a FIFO for monkeypatched ``input``."""

    def __init__(self, scripted: list[str]):
        self._scripted = list(scripted)

    def __call__(self, prompt: str = "") -> str:
        if not self._scripted:
            raise AssertionError(
                f"FakeInput exhausted; CLI asked for more input. Prompt={prompt!r}"
            )
        return self._scripted.pop(0)


def test_main_dry_run(monkeypatch, tmp_path, db_conn, _seeded_corpus):
    """End-to-end smoke: 2 draft queries → 2 accepted tuples + manifest."""
    from app.eval import author

    monkeypatch.setattr(author, "get_embedder", lambda: _StubEmbedder())

    qfile = tmp_path / "QUERIES.md"
    qfile.write_text(
        "# === seed queries ===\n"
        "What amp setting for seed 0?\n"
        "What overdrive for seed 1?\n",
        encoding="utf-8",
    )
    out_jsonl = tmp_path / "golden.jsonl"
    held_out = tmp_path / "HELD_OUT.md"

    scripted = [
        # ---- query 1 ----
        "1",              # accept candidate 1
        "amp_settings",   # themes
        "N",              # not held out
        # ---- query 2 ----
        "1,2",            # accept candidates 1 and 2
        "pedal_choice",   # themes
        "y",              # held out
    ]
    monkeypatch.setattr("builtins.input", _FakeInput(scripted))

    rc = author.main(
        [
            "--queries",
            str(qfile),
            "--output",
            str(out_jsonl),
            "--held-out-manifest",
            str(held_out),
            "--k",
            "8",
        ]
    )
    assert rc == 0
    assert out_jsonl.exists()
    tuples = load_golden_set(out_jsonl)
    assert len(tuples) == 2
    assert tuples[0].query == "What amp setting for seed 0?"
    assert tuples[0].expected_themes == ["amp_settings"]
    assert tuples[0].held_out is False
    assert tuples[1].expected_themes == ["pedal_choice"]
    assert tuples[1].held_out is True
    assert len(tuples[1].expected_chunk_ids) == 2

    body = held_out.read_text(encoding="utf-8")
    assert re.search(r"no retrieval tuning has been performed", body, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Test 8 (static): the SQL uses %s placeholders and the cosine <=> operator.
# ---------------------------------------------------------------------------


def test_author_sql_uses_pgvector_cosine_operator():
    src = Path(__file__).resolve().parent.parent / "app" / "eval" / "author.py"
    contents = src.read_text(encoding="utf-8")
    # Cosine distance operator from pgvector — required for retrieval.
    assert "embedding <=>" in contents
    # All SQL must be parameterized.
    assert "%s" in contents


# ---------------------------------------------------------------------------
# Test 9 (static): CLI exposes the four flags the plan locks.
# ---------------------------------------------------------------------------


def test_author_help_lists_locked_flags(capsys):
    from app.eval.author import build_parser

    parser = build_parser()
    help_text = parser.format_help()
    for flag in ("--queries", "--output", "--held-out-manifest", "--k"):
        assert flag in help_text, f"missing flag {flag} in --help output"
