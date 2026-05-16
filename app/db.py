"""psycopg3 connection helper with pgvector pre-registered.

This module is the ONLY path the rest of ``app/`` uses to open a Postgres
connection. ``register_vector(conn)`` runs on every new connection so callers
can pass Python ``list[float]`` / numpy arrays directly as ``vector`` parameters
via ``%s`` placeholders — no f-string SQL anywhere.

There is intentionally no connection pool in Phase 1. The only consumer is the
offline ingestion CLI (``python -m app.ingest.pipeline``) plus the smoke tests.
Pooling is Phase 3's job once the FastAPI request path exists.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from app.config import get_settings

# scripts/init_db.sql sits at <project_root>/scripts/init_db.sql; app/db.py is
# at <project_root>/app/db.py, so two .parent hops land us at the root.
_INIT_SQL_PATH = Path(__file__).resolve().parent.parent / "scripts" / "init_db.sql"


def get_conn() -> psycopg.Connection:
    """Open a fresh psycopg3 connection with pgvector adapters registered.

    The connection is returned in autocommit=False (psycopg default); callers
    own transaction boundaries via ``conn.commit()`` / ``conn.rollback()`` or
    ``with conn.transaction(): ...``.
    """

    conn = psycopg.connect(get_settings().database_url)
    register_vector(conn)
    return conn


def init_schema(conn: psycopg.Connection | None = None) -> None:
    """Execute ``scripts/init_db.sql`` against ``conn`` (or a fresh connection).

    The DDL is idempotent — every object uses ``IF NOT EXISTS`` so re-running
    against a populated database is a no-op. When ``conn`` is None, this opens
    a connection, commits, and closes it; otherwise it executes inside the
    caller's transaction and commits at the end.
    """

    ddl = _INIT_SQL_PATH.read_text(encoding="utf-8")

    if conn is None:
        with get_conn() as owned:
            with owned.cursor() as cur:
                cur.execute(ddl)
            owned.commit()
        return

    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()
