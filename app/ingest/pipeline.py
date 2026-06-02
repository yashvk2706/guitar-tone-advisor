"""Ingestion CLI — ``python -m app.ingest.pipeline``.

Wires together the loader → chunker → embedder → writer pipeline. This is
the only entry point that touches all four; ``app.api`` (Phase 3) reads from
the resulting ``chunks`` table but never invokes this module.

Lifecycle per invocation:

1. Construct the embedder via the factory (single ``get_embedder()`` call —
   not per document — so the embedder's ``.model`` attribute is the one
   stored on ``ingest_runs`` and every ``chunks`` row).
2. Open one Postgres connection. ``start_run`` writes the audit row.
3. If ``--full-rebuild``, ``truncate_all(conn)`` empties ``chunks`` +
   ``documents`` before iteration. ``ingest_runs`` is preserved.
4. Iterate every ``RawDocument`` from ``load_forum_posts(args.forum_dir)``:
   ``upsert_document`` → ``chunk_document`` → ``chunks_to_embed`` partition →
   embed only the new/changed chunks → ``upsert_chunks``. ``conn.commit()``
   per document gives partial durability if the next document crashes.
5. On clean exit, ``complete_run`` records the final counters and commits.
6. On exception, the main transaction is rolled back **and** a fresh
   connection writes ``fail_run`` so the audit row survives — T-04-08
   mitigation. The exception is re-raised so the process exits non-zero.

CLAUDE.md hard constraints honored here:
    - No direct ``openai`` import (only ``get_embedder()``).
    - All DB writes flow through ``app.ingest.writer`` (which uses ``%s``).
    - Source-type dispatch via ``chunk_document`` — no universal chunker.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.db import get_conn
from app.embeddings.factory import get_embedder
from app.ingest.chunker import chunk_document
from app.ingest.loader import (
    load_forum_posts,
    load_pdf_manuals,
    load_youtube_transcripts,
    load_web_articles,
)
from app.ingest.writer import (
    chunks_to_embed,
    complete_run,
    fail_run,
    start_run,
    truncate_all,
    upsert_chunks,
    upsert_document,
)

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.ingest.pipeline",
        description=(
            "Ingest raw_data/forum_posts/ into chunks (Phase 1). "
            "Idempotent on re-run via content-hash dedup."
        ),
    )
    parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help=(
            "Truncate chunks and documents before ingesting (D-04 escape "
            "hatch). ingest_runs is preserved so the audit trail survives."
        ),
    )
    parser.add_argument(
        "--forum-dir",
        default="raw_data/forum_posts",
        help="Directory containing forum .txt files (default: raw_data/forum_posts).",
    )
    parser.add_argument(
        "--manuals-dir",
        default="raw_data/manuals",
        help="Directory containing PDF manual files (default: raw_data/manuals).",
    )
    parser.add_argument(
        "--youtube-ids",
        default="raw_data/youtube_ids.txt",
        help="File of YouTube video IDs, one per line (default: raw_data/youtube_ids.txt).",
    )
    parser.add_argument(
        "--article-urls",
        default="raw_data/article_urls.txt",
        help="File of article URLs, one per line (default: raw_data/article_urls.txt).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the ingestion pipeline. Returns process exit code."""

    # Wire up logging once per invocation. ``force=True`` so re-imports
    # during tests don't end up with a no-op basicConfig.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    parser = _build_parser()
    args = parser.parse_args(argv)

    embedder = get_embedder()  # raises if EMBEDDING_MODEL is unimplemented

    conn = get_conn()
    try:
        run_id = start_run(conn, embedder.model, args.full_rebuild)
        conn.commit()  # audit row first — visible even if a later step crashes
    except Exception:
        conn.close()
        raise

    try:
        if args.full_rebuild:
            logger.info("--full-rebuild: truncating chunks and documents")
            truncate_all(conn)
            conn.commit()

        raw_docs = load_forum_posts(Path(args.forum_dir))
        total_inserted = 0
        total_skipped = 0
        n = len(raw_docs)
        logger.info("Loaded %d raw documents from %s", n, args.forum_dir)

        for i, raw_doc in enumerate(raw_docs, start=1):
            doc_id = upsert_document(conn, raw_doc)
            chunks = chunk_document(raw_doc)
            to_embed, to_skip = chunks_to_embed(
                conn, doc_id, chunks, embedder.model
            )
            total_skipped += len(to_skip)
            if to_embed:
                result = embedder.embed_documents([c.text for c in to_embed])
                upsert_chunks(
                    conn,
                    doc_id,
                    to_embed,
                    result.vectors,
                    embedder.model,
                    source_type=raw_doc.source_type,
                )
                total_inserted += len(to_embed)
            # Per-document commit: a mid-run crash leaves a valid prefix of
            # the corpus in chunks rather than rolling back the entire run.
            conn.commit()
            logger.info(
                "[%d/%d] %s: +%d chunks, =%d skipped",
                i,
                n,
                raw_doc.source_id,
                len(to_embed),
                len(to_skip),
            )

        # --- PDF manuals ---
        # Count total attempted before loading (failed PDFs are logged + skipped
        # inside the loader, so total_attempted = glob count, not len(loaded)).
        manuals_dir = Path(args.manuals_dir)
        n_pdf_total = len(list(manuals_dir.glob("*.pdf"))) if manuals_dir.exists() else 0
        pdf_docs = load_pdf_manuals(manuals_dir) if manuals_dir.exists() else []
        n_pdf_ingested = 0
        n_pdf_loader_skipped = 0
        logger.info("Loaded %d PDF manuals from %s", len(pdf_docs), args.manuals_dir)

        for i, raw_doc in enumerate(pdf_docs, start=1):
            doc_id = upsert_document(conn, raw_doc)
            chunks = chunk_document(raw_doc)
            to_embed, to_skip = chunks_to_embed(
                conn, doc_id, chunks, embedder.model
            )
            total_skipped += len(to_skip)
            if to_embed:
                result = embedder.embed_documents([c.text for c in to_embed])
                upsert_chunks(
                    conn,
                    doc_id,
                    to_embed,
                    result.vectors,
                    embedder.model,
                    source_type=raw_doc.source_type,
                )
                total_inserted += len(to_embed)
                n_pdf_ingested += 1
            conn.commit()
            logger.info(
                "[pdf %d/%d] %s: +%d chunks, =%d skipped",
                i,
                len(pdf_docs),
                raw_doc.source_id,
                len(to_embed),
                len(to_skip),
            )

        # Count PDFs the loader skipped (corrupted / both extractors failed).
        n_pdf_loader_skipped = n_pdf_total - len(pdf_docs)

        # --- YouTube transcripts ---
        youtube_ids_file = Path(args.youtube_ids)
        if youtube_ids_file.exists():
            from app.ingest.loader import _parse_youtube_ids  # private but same module
            n_yt_total = len(_parse_youtube_ids(youtube_ids_file))
            yt_docs = load_youtube_transcripts(youtube_ids_file)
        else:
            n_yt_total = 0
            yt_docs = []
        n_yt_ingested = 0
        logger.info("Loaded %d YouTube transcripts from %s", len(yt_docs), args.youtube_ids)

        for i, raw_doc in enumerate(yt_docs, start=1):
            doc_id = upsert_document(conn, raw_doc)
            chunks = chunk_document(raw_doc)
            to_embed, to_skip = chunks_to_embed(
                conn, doc_id, chunks, embedder.model
            )
            total_skipped += len(to_skip)
            if to_embed:
                result = embedder.embed_documents([c.text for c in to_embed])
                upsert_chunks(
                    conn,
                    doc_id,
                    to_embed,
                    result.vectors,
                    embedder.model,
                    source_type=raw_doc.source_type,
                )
                total_inserted += len(to_embed)
                n_yt_ingested += 1
            conn.commit()
            logger.info(
                "[yt %d/%d] %s: +%d chunks, =%d skipped",
                i,
                len(yt_docs),
                raw_doc.source_id,
                len(to_embed),
                len(to_skip),
            )

        n_yt_skipped = n_yt_total - len(yt_docs)

        # --- Web articles ---
        article_urls_file = Path(args.article_urls)
        if article_urls_file.exists():
            n_art_total = sum(
                1
                for line in article_urls_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
            art_docs = load_web_articles(article_urls_file)
        else:
            n_art_total = 0
            art_docs = []
        n_art_ingested = 0
        logger.info("Loaded %d web articles from %s", len(art_docs), args.article_urls)

        for i, raw_doc in enumerate(art_docs, start=1):
            doc_id = upsert_document(conn, raw_doc)
            chunks = chunk_document(raw_doc)
            to_embed, to_skip = chunks_to_embed(
                conn, doc_id, chunks, embedder.model
            )
            total_skipped += len(to_skip)
            if to_embed:
                result = embedder.embed_documents([c.text for c in to_embed])
                upsert_chunks(
                    conn,
                    doc_id,
                    to_embed,
                    result.vectors,
                    embedder.model,
                    source_type=raw_doc.source_type,
                )
                total_inserted += len(to_embed)
                n_art_ingested += 1
            conn.commit()
            logger.info(
                "[art %d/%d] %s: +%d chunks, =%d skipped",
                i,
                len(art_docs),
                raw_doc.source_id,
                len(to_embed),
                len(to_skip),
            )

        n_art_skipped = n_art_total - len(art_docs)

        # Aggregate document count across all source types for the audit row.
        all_docs_count = len(raw_docs) + len(pdf_docs) + len(yt_docs) + len(art_docs)
        complete_run(
            conn,
            run_id=run_id,
            n_documents=all_docs_count,
            n_chunks_inserted=total_inserted,
            n_chunks_skipped=total_skipped,
        )
        conn.commit()
        print(
            f"OK: {total_inserted} chunks inserted, "
            f"{total_skipped} skipped across {all_docs_count} documents."
        )
        # D-07: per-source end-of-run summary lines (print, not logger.info,
        # so they always appear in stdout regardless of log level).
        print(f"PDFs: {n_pdf_ingested} of {n_pdf_total} ingested ({n_pdf_loader_skipped} skipped)")
        print(f"Transcripts: {n_yt_ingested} of {n_yt_total} ingested ({n_yt_skipped} skipped)")
        print(f"Articles: {n_art_ingested} of {n_art_total} ingested ({n_art_skipped} skipped)")
        return 0
    except Exception as e:
        # Main transaction is poisoned — roll it back so we can close cleanly.
        try:
            conn.rollback()
        except Exception:  # pragma: no cover — best-effort cleanup
            pass

        # T-04-08 mitigation: write the audit row through a *fresh*
        # connection so it survives the main rollback. T-04-05: use repr(e)
        # to avoid leaking traceback frames / SDK request bodies into the
        # audit row.
        try:
            with get_conn() as fresh:
                fail_run(fresh, run_id, repr(e))
                fresh.commit()
        except Exception as audit_err:  # pragma: no cover — surface both
            logger.error(
                "Could not write fail_run audit row: %r (original: %r)",
                audit_err,
                e,
            )

        print(f"FAILED: {e!r}", file=sys.stderr)
        raise
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover — best-effort
            pass


if __name__ == "__main__":  # pragma: no cover — invoked via python -m
    sys.exit(main())
