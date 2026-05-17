"""Interactive CLI for authoring the golden eval set (Plan 01-05 / EVAL-01).

Reads draft queries from ``eval/QUERIES.md`` (one per line; ``#`` comments
and blanks ignored), embeds each query through the locked Embedder
Protocol, and SELECTs the top-K candidate chunks by cosine distance.
For each query the human reviewer accepts / rejects candidates by 1-based
index, supplies one or more themes from the closed enum (D-09), and
flags whether the tuple is held out (D-10).

The CLI writes the validated tuples to ``eval/golden_set.jsonl`` via
``save_golden_set`` and emits ``eval/HELD_OUT.md`` carrying the ISO-8601
UTC timestamp + held-out indices + the explicit "no retrieval tuning has
been performed" audit statement (D-11).

CLAUDE.md hard constraints honoured here:

* Embedding always flows through ``get_embedder()`` — never an ``import
  openai`` in this module. The ``tests/test_eval_author.py::
  test_no_direct_openai_import`` grep enforces this statically.
* All SQL uses psycopg ``%s`` parameter binding; the only variables in
  the query are the embedded vector and the integer ``k``. Free-form
  query text is consumed by ``embedder.embed_query`` (a Python call) and
  never interpolated into SQL.
* Chunk UUIDs are read live from the DB (D-07: "no manual transcription").

Run it with::

    python -m app.eval.author
        [--queries eval/QUERIES.md]
        [--output eval/golden_set.jsonl]
        [--held-out-manifest eval/HELD_OUT.md]
        [--k 8]
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

import psycopg

from app.db import get_conn
from app.embeddings.factory import get_embedder
from app.eval.schema import (
    VALID_THEMES,
    GoldenTuple,
    save_golden_set,
)


# Default file locations relative to the project root. Operator can
# override via the CLI flags below.
_DEFAULT_QUERIES = Path("eval/QUERIES.md")
_DEFAULT_OUTPUT = Path("eval/golden_set.jsonl")
_DEFAULT_HELD_OUT = Path("eval/HELD_OUT.md")
_DEFAULT_K = 8

# How many characters of chunk text to show the reviewer per candidate.
# Long enough to recognize provenance; short enough to keep the prompt
# scannable on an 80-column terminal.
_PREVIEW_CHARS = 200


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without DB or embedder)
# ---------------------------------------------------------------------------


def read_queries(path: Path) -> list[str]:
    """Return the non-comment, non-blank lines of ``path`` in order.

    A line whose stripped content starts with ``#`` is a comment. Blank
    lines (after strip) are also dropped. Whitespace around the content
    is collapsed via ``.strip()``.
    """
    path = Path(path)
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def parse_accept_input(raw: str, candidates_count: int) -> list[int] | None:
    """Parse the reviewer's accept-input into 0-based indices.

    Semantics:
        * ``"skip"`` (case-insensitive, surrounding whitespace ok) → ``None``
          tells the caller to drop this draft query without recording a
          tuple.
        * Empty / whitespace-only input → ``[]`` is interpreted as
          "no candidates accepted" — also drops the query (the eval set
          requires non-empty ``expected_chunk_ids``).
        * Otherwise: split on ``,``, parse each token as an integer
          1-based index, subtract 1, and verify every result lies in
          ``[0, candidates_count)``. Out-of-range or non-integer input
          raises ``ValueError`` so the CLI re-prompts.
    """
    s = raw.strip()
    if s.lower() == "skip":
        return None
    if not s:
        return []

    indices: list[int] = []
    for tok in s.split(","):
        tok = tok.strip()
        try:
            n = int(tok)
        except ValueError as e:
            raise ValueError(
                f"Not an integer: {tok!r}. Enter comma-separated 1-based "
                f"indices like '1,3,4' or 'skip'."
            ) from e
        # 1-based indices: 1..candidates_count inclusive.
        if n < 1 or n > candidates_count:
            raise ValueError(
                f"Index {n} out of range; expected 1..{candidates_count}."
            )
        indices.append(n - 1)
    return indices


def parse_themes(raw: str) -> list[str]:
    """Parse ``raw`` as a comma-separated list of theme labels.

    Every parsed label MUST be in :data:`VALID_THEMES` (D-09 closed enum).
    Empty / whitespace-only input raises ``ValueError`` — themes are
    required and cannot be elided.
    """
    s = raw.strip()
    if not s:
        raise ValueError(
            f"At least one theme is required. Valid choices: {VALID_THEMES}"
        )

    themes: list[str] = []
    for tok in s.split(","):
        t = tok.strip()
        if not t:
            continue
        if t not in VALID_THEMES:
            raise ValueError(
                f"Invalid theme: {t!r}; valid choices: {VALID_THEMES}"
            )
        themes.append(t)
    if not themes:
        raise ValueError(
            f"At least one theme is required. Valid choices: {VALID_THEMES}"
        )
    return themes


def _utc_iso_now() -> str:
    """Current UTC time in ISO-8601 format (seconds precision)."""
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds")
    )


def write_held_out_md(
    path: Path,
    tuples: list[GoldenTuple],
    held_out_sources: list[str],
) -> None:
    """Write ``eval/HELD_OUT.md`` with the locked-at timestamp + indices.

    The body MUST contain the literal phrase
    ``no retrieval tuning has been performed`` (case-insensitive grep
    matches it during Phase 2 plan-check) and the list of held-out
    indices in 0-based JSONL line order. Held-out source filenames are
    listed for human auditability.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    held_out_indices = [i for i, t in enumerate(tuples) if t.held_out]
    locked_at = _utc_iso_now()

    src_lines = "\n".join(f"- {src}" for src in held_out_sources) or "- (none)"

    body = (
        "# Held-Out Golden Eval Set\n"
        "\n"
        f"**Locked at:** {locked_at}  (ISO-8601 UTC)\n"
        f"**Total tuples:** {len(tuples)}\n"
        f"**Held-out indices (0-based, matching golden_set.jsonl line order):** "
        f"{held_out_indices}\n"
        "**Statement:** No retrieval tuning has been performed at the time of "
        "this commit.\n"
        "Recall@K and MRR (Phase 5) will be measured against these held-out "
        "indices,\n"
        "which are sourced from the following forum topics:\n"
        f"{src_lines}\n"
        "\n"
        "**Audit:** This file MUST be committed to git BEFORE any Phase 2 "
        "retrieval parameter\n"
        "(K, expansion strategy, alias map content) is touched.\n"
    )
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# DB helper — retrieve top-K candidate chunks for a draft query.
# ---------------------------------------------------------------------------


def retrieve_candidates(
    conn: psycopg.Connection,
    embedder,
    query: str,
    k: int = _DEFAULT_K,
) -> list[dict]:
    """Return the top-``k`` chunks by cosine distance to ``query``.

    Embedding flows through the Embedder Protocol (``embed_query``); the
    SQL query binds the vector + integer ``k`` via ``%s`` placeholders.
    Returned dicts carry the four fields the interactive prompt needs:
    ``chunk_id`` (str), ``chunk_text`` (str), ``source_filename`` (str),
    and the chunk's ``metadata_json`` dict (forwarded for future
    inspection — not currently displayed).
    """
    q_vec = embedder.embed_query(query)

    # The cosine operator <=> is pgvector's built-in distance for the
    # vector_cosine_ops opclass on the HNSW index (see scripts/init_db.sql).
    # Both vector and k bind through %s — no f-string SQL anywhere.
    sql = """
        SELECT
            c.id::text       AS chunk_id,
            c.chunk_text     AS chunk_text,
            c.metadata_json  AS metadata_json,
            d.source_id      AS source_filename
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """
    out: list[dict] = []
    with conn.cursor() as cur:
        cur.execute(sql, (q_vec, k))
        rows = cur.fetchall()
        for row in rows:
            chunk_id, chunk_text, metadata_json, source_filename = row
            # psycopg returns JSONB as a dict by default; defend against
            # the str-shape edge case for older driver builds.
            if isinstance(metadata_json, str):
                import json as _json

                metadata_json = _json.loads(metadata_json)
            out.append(
                {
                    "chunk_id": str(chunk_id),
                    "chunk_text": chunk_text,
                    "source_filename": source_filename,
                    "metadata_json": metadata_json or {},
                }
            )
    return out


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------


def _format_candidate(idx_1based: int, cand: dict) -> str:
    """Return the one-line preview string for a single candidate."""
    preview = (cand["chunk_text"] or "").strip().replace("\n", " ")
    if len(preview) > _PREVIEW_CHARS:
        preview = preview[:_PREVIEW_CHARS].rstrip() + "..."
    return f"  [{idx_1based}] ({cand['source_filename']}) {preview}"


def _prompt_accept_indices(candidates: list[dict]) -> list[int] | None:
    """Loop on parse errors until the reviewer gives a valid accept-input."""
    while True:
        raw = input(
            'Accept which chunks for this query? (e.g. "1,3,4" or "skip"): '
        )
        try:
            return parse_accept_input(raw, len(candidates))
        except ValueError as e:
            print(f"  ! {e}  Try again.")


def _prompt_themes() -> list[str]:
    """Loop on parse errors until the reviewer gives valid themes."""
    while True:
        raw = input(
            f"Themes (comma-separated, choices: {', '.join(VALID_THEMES)}): "
        )
        try:
            return parse_themes(raw)
        except ValueError as e:
            print(f"  ! {e}  Try again.")


def _prompt_held_out() -> bool:
    """Default N. Anything starting with 'y'/'Y' is True."""
    raw = input("Held out? (y/N): ").strip().lower()
    return raw.startswith("y")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.eval.author",
        description=(
            "Interactive authoring CLI for the Phase 1 golden eval set "
            "(EVAL-01). Reads draft queries from --queries, surfaces top-K "
            "candidate chunks per query, captures human accept/reject + "
            "themes + held_out flags, and writes golden_set.jsonl + "
            "HELD_OUT.md."
        ),
    )
    p.add_argument(
        "--queries",
        type=Path,
        default=_DEFAULT_QUERIES,
        help="Path to the draft-queries Markdown file (one query per line; "
        "'#'-prefixed and blank lines ignored). Default: %(default)s",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="Path to write the JSONL golden set. Default: %(default)s",
    )
    p.add_argument(
        "--held-out-manifest",
        type=Path,
        default=_DEFAULT_HELD_OUT,
        help="Path to write the held-out manifest (D-10, D-11). "
        "Default: %(default)s",
    )
    p.add_argument(
        "--k",
        type=int,
        default=_DEFAULT_K,
        help="Number of candidate chunks to surface per draft query. "
        "Default: %(default)s",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Build the embedder BEFORE opening the DB — a factory error (e.g.,
    # unknown EMBEDDING_MODEL) should fail before we touch Postgres.
    embedder = get_embedder()

    queries = read_queries(args.queries)
    if not queries:
        print(f"No draft queries found in {args.queries}", file=sys.stderr)
        return 1

    print(
        f"Loaded {len(queries)} draft queries from {args.queries}. "
        f"For each query, accept candidates by 1-based index, type 'skip' to "
        f"drop, then tag themes + held_out.\n"
    )

    accepted: list[GoldenTuple] = []
    # Track the source filename per accepted tuple for the held-out manifest.
    accepted_sources: list[str] = []
    skipped: list[str] = []

    conn = get_conn()
    try:
        for q_idx, query in enumerate(queries, start=1):
            print(f"=== Query {q_idx}/{len(queries)}: {query}")
            candidates = retrieve_candidates(conn, embedder, query, k=args.k)
            if not candidates:
                print("  (no candidates returned — chunks table empty?)\n")
                skipped.append(query)
                continue

            for i, cand in enumerate(candidates, start=1):
                print(_format_candidate(i, cand))

            indices = _prompt_accept_indices(candidates)
            if indices is None:
                # "skip" path: do NOT record a tuple.
                print("  (skipped)\n")
                skipped.append(query)
                continue
            if not indices:
                # Empty input: same effect — we cannot construct a tuple
                # with an empty expected_chunk_ids list, so treat as skip.
                print(
                    "  (no chunks accepted — recording as skipped to satisfy "
                    "non-empty expected_chunk_ids)\n"
                )
                skipped.append(query)
                continue

            themes = _prompt_themes()
            held_out = _prompt_held_out()

            chunk_ids = [candidates[i]["chunk_id"] for i in indices]
            # Use the FIRST accepted candidate's source filename as the
            # representative source for held-out manifest reporting.
            primary_source = candidates[indices[0]]["source_filename"]

            try:
                t = GoldenTuple(
                    query=query,
                    expected_chunk_ids=chunk_ids,
                    expected_themes=themes,
                    held_out=held_out,
                )
            except Exception as e:
                # Pydantic ValidationError is the expected failure here;
                # surface and re-prompt would require restructuring the loop.
                # In practice the parse_* helpers have already validated
                # everything, so this branch is the safety net.
                print(f"  ! Validation failed: {e}; dropping this query.\n")
                skipped.append(query)
                continue

            accepted.append(t)
            accepted_sources.append(primary_source)
            print(
                f"  recorded {len(chunk_ids)} chunk(s), themes={themes}, "
                f"held_out={held_out}\n"
            )
    finally:
        conn.close()

    # Write outputs even if zero tuples accepted — the user gets an empty
    # golden_set.jsonl and an empty HELD_OUT.md they can re-run.
    save_golden_set(accepted, args.output)

    held_out_sources = [
        accepted_sources[i] for i, t in enumerate(accepted) if t.held_out
    ]
    write_held_out_md(args.held_out_manifest, accepted, held_out_sources)

    # Final summary.
    print("=" * 60)
    print(f"Total tuples authored:  {len(accepted)}")
    print(f"Held-out count:         {sum(1 for t in accepted if t.held_out)}")
    print(f"Skipped queries:        {len(skipped)}")
    print(f"Output JSONL:           {args.output}")
    print(f"Held-out manifest:      {args.held_out_manifest}")
    if accepted:
        by_source: dict[str, int] = {}
        for src in accepted_sources:
            by_source[src] = by_source.get(src, 0) + 1
        print("Distribution by source_filename:")
        for src in sorted(by_source):
            print(f"  {src}: {by_source[src]}")
    if skipped:
        print("Skipped queries (re-author or remove from QUERIES.md):")
        for q in skipped:
            print(f"  - {q}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
