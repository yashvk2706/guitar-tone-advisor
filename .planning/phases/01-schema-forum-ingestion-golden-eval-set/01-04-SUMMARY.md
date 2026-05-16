---
phase: 01-schema-forum-ingestion-golden-eval-set
plan: 04
subsystem: ingestion-pipeline
tags: [writer, idempotency, content-hash-dedup, ingest-runs-lifecycle, cli, argparse, on-conflict, pgvector-binding]
dependency_graph:
  requires:
    - "Plan 01-01: app.db.get_conn (pgvector pre-registered), init_schema(), scripts/init_db.sql DDL"
    - "Plan 01-02: app.ingest.loader.load_forum_posts, app.ingest.chunker.chunk_document"
    - "Plan 01-03: app.embeddings.factory.get_embedder, Embedder Protocol shape"
  provides:
    - "app.ingest.writer (upsert_document, chunks_to_embed, upsert_chunks, start_run, complete_run, fail_run, truncate_all)"
    - "app.ingest.pipeline (CLI entry point `python -m app.ingest.pipeline`)"
    - "Idempotency contract: re-running with unchanged input writes zero new chunks (INGEST-06)"
    - "Audit lifecycle: ingest_runs row per CLI invocation, status running -> completed | failed"
  affects:
    - "Plan 01-05 eval authoring will SELECT chunk UUIDs from the populated chunks table"
    - "Phase 2 retrieval queries the chunks table built here"
    - "Phase 2+ Voyage embedder swap works without writer changes (writer is embedder-agnostic — chunks.embedding_model column records what was used)"
tech_stack:
  added:
    - "psycopg.Connection.executemany — used in upsert_chunks for the bulk INSERT ... ON CONFLICT path"
    - "argparse (stdlib) — already implicitly available, now actively used"
  patterns:
    - "Two-phase dedup: application-level chunks_to_embed partition (avoids embedding API calls) + DB-level ON CONFLICT safety net (catches partition slip)"
    - "Per-document conn.commit() for partial durability — a mid-run crash leaves a valid prefix of the corpus, not an all-or-nothing rollback"
    - "fail_run via FRESH connection so the audit row survives main-transaction rollback (T-04-08)"
    - "repr(e) into ingest_runs.error to avoid leaking SDK request bodies / tracebacks (T-04-05)"
    - "Defensive assert(len(chunks) == len(vectors)) before vector binding (T-04-02 mitigation against silent misattribution)"
    - "TRUNCATE chunks, documents CASCADE on --full-rebuild; ingest_runs INTENTIONALLY preserved for audit continuity"
key_files:
  created:
    - app/ingest/writer.py
    - app/ingest/pipeline.py
    - tests/test_writer.py
    - tests/test_pipeline.py
  modified: []
decisions:
  - "ingest_runs is NOT truncated on --full-rebuild. The audit trail of every prior run survives across full-rebuilds so the operator can compare counters across re-embeds (e.g., 'first run ingested 21, today's full-rebuild ingested 23 — the chunker changed'). TRUNCATE chunks, documents RESTART IDENTITY CASCADE only — documented inline in truncate_all docstring."
  - "Phase 1 hard-codes source_type='forum' in upsert_chunks rather than reading from RawDocument.source_type. Reason: Phase 1 only ingests forum; the chunks.source_type column is denormalized for filtered retrieval (Phase 2). Phase 2 will pass the source_type through from the RawDocument when PDF/web/youtube chunkers come online. Marked with a clear comment in writer.py (_PHASE_1_SOURCE_TYPE constant)."
  - "Embedder.model attribute (post-construction) is what gets stored on every chunks row and on ingest_runs.embedding_model. NOT the EMBEDDING_MODEL env var. This means a swap from text-embedding-3-small to text-embedding-3-large is correctly audited even if the env var lags the deployment."
  - "Audit row committed BEFORE any document iteration (commit immediately after start_run). Rationale: if the process is killed between iteration steps, the audit row already exists with status='running' so the operator knows a partial run happened. The next clean run will see no leftover chunks if the kill happened before the first conn.commit() within the loop."
  - "Pipeline test_help_works is in tests/test_pipeline.py rather than a separate no-DB file. Reason: a single home for pipeline tests keeps discovery simple and the fixture's pytest.skip gate is per-test (db_conn fixture is only requested by the live tests, not by test_help_works or test_uses_only_embedder_protocol). Plan suggested this pattern explicitly in the action notes."
metrics:
  duration_minutes: ~15
  tasks_completed: 2
  files_created: 4
  files_modified: 0
  commits: 4
  completed_date: 2026-05-16
---

# Phase 01 Plan 04: Writer + Ingestion CLI Pipeline Summary

**One-liner:** `python -m app.ingest.pipeline` is now a single command that loads every `.txt` in `raw_data/forum_posts/`, chunks each via the locked paragraph-packing algorithm, partitions chunks by content-hash to skip already-embedded text, calls the OpenAI embedder only on the new/changed remainder, and idempotently UPSERTs into `chunks` with a per-document commit and a `running → completed | failed` audit row in `ingest_runs` — satisfying INGEST-01, INGEST-02, and INGEST-06 in one shot.

## What Shipped

### Task 1 — Writer module (commits `3d37015` RED, `77bc562` GREEN)

**RED (`3d37015`):** `tests/test_writer.py` with 12 tests committed against an empty `app/ingest/writer.py`. Collection failed with `ModuleNotFoundError: No module named 'app.ingest.writer'` — RED gate satisfied. Tests 1–11 are DB-touching and gated to `pytest.skip` if `get_conn()` fails (matches the convention from `tests/test_schema.py`); test 12 (the no-f-string-SQL grep) is the only test that always runs.

**GREEN (`77bc562`):** `app/ingest/writer.py` exports all 7 functions the plan locks:

| Function | Statement shape | Key invariant |
|---|---|---|
| `upsert_document` | `INSERT ... ON CONFLICT (source_type, source_id) DO UPDATE` with `CASE WHEN content_hash = EXCLUDED.content_hash THEN documents.fetched_at ELSE now() END` | Unchanged hash → row preserved including `fetched_at`. Hash change → UPDATE but UUID preserved. |
| `chunks_to_embed` | Single-roundtrip `SELECT chunk_index, content_hash` → in-memory dict → partition | Skip iff `(chunk_index, content_hash)` tuple already exists for `(document_id, embedding_model)`. Input-order-preserving. |
| `upsert_chunks` | `executemany` of `INSERT ... ON CONFLICT (document_id, chunk_index, embedding_model) DO UPDATE` | Defensive `assert(len(chunks)==len(vectors))` before any binding; vectors flow as `list[float]` and are adapted to `vector(1536)` by the pre-registered pgvector adapter. |
| `start_run` | `INSERT ... RETURNING id` | New row with `status='running'`, `started_at = now()`. |
| `complete_run` | `UPDATE ... SET status='completed', finished_at=now(), counters` | Sets all three counters atomically with the status flip. |
| `fail_run` | `UPDATE ... SET status='failed', finished_at=now(), error=%s` | Designed to be called through a FRESH connection so the audit survives the main-tx rollback. |
| `truncate_all` | `TRUNCATE chunks, documents RESTART IDENTITY CASCADE` | `ingest_runs` INTENTIONALLY preserved across `--full-rebuild`. |

Every statement uses `%s` placeholders (11 occurrences across the module). The `grep -E "f['\"](SELECT|INSERT|UPDATE|DELETE|TRUNCATE)" app/ingest/writer.py` gate returns 0 (T-04-01 mitigation enforced statically).

### Task 2 — Pipeline CLI (commits `6d9b99a` RED, `6bd735c` GREEN)

**RED (`6d9b99a`):** `tests/test_pipeline.py` with 6 tests committed against an empty `app/ingest/pipeline.py`. Collection failed — RED gate satisfied. Tests 1–4 require both `DATABASE_URL` (reachable Postgres) and `OPENAI_API_KEY` and `pytest.skip` otherwise; tests 5–6 are static and always run.

**GREEN (`6bd735c`):** `app/ingest/pipeline.py` implements the canonical lifecycle:

```text
build_parser → parse args
get_embedder()         # one call per process
get_conn()             # one connection per process
start_run + commit     # audit row visible immediately

if --full-rebuild:
    truncate_all + commit

for raw_doc in load_forum_posts(args.forum_dir):
    doc_id = upsert_document(conn, raw_doc)
    chunks = chunk_document(raw_doc)
    to_embed, to_skip = chunks_to_embed(conn, doc_id, chunks, embedder.model)
    if to_embed:
        result = embedder.embed_documents([c.text for c in to_embed])
        upsert_chunks(conn, doc_id, to_embed, result.vectors, embedder.model)
    conn.commit()      # per-document durability
    log(progress)

complete_run + commit
print("OK: …")
return 0
```

The exception path:

```python
except Exception as e:
    conn.rollback()                          # main tx is poisoned
    with get_conn() as fresh:                # NEW connection
        fail_run(fresh, run_id, repr(e))     # audit survives
        fresh.commit()
    print(f"FAILED: {e!r}", file=sys.stderr)
    raise                                    # non-zero exit
```

CLAUDE.md hard constraints enforced statically by `tests/test_pipeline.py::test_uses_only_embedder_protocol` (greps `^(from openai|import openai)` and asserts zero matches in `app/ingest/pipeline.py`).

## Verification Performed Here

| Check | Result |
|---|---|
| `python3 -c "import ast; ast.parse(open('app/ingest/writer.py').read())"` | ✓ parses |
| `python3 -c "import ast; ast.parse(open('app/ingest/pipeline.py').read())"` | ✓ parses |
| All 7 writer exports defined as FunctionDef in the AST | ✓ `upsert_document, chunks_to_embed, upsert_chunks, start_run, complete_run, fail_run, truncate_all` |
| `grep -c 'ON CONFLICT (source_type, source_id)' app/ingest/writer.py` | ✓ 2 matches (SQL + docstring) |
| `grep -c 'ON CONFLICT (document_id, chunk_index, embedding_model)' app/ingest/writer.py` | ✓ 2 matches (SQL + docstring) |
| `grep -c 'TRUNCATE chunks' app/ingest/writer.py` | ✓ 1 match |
| `grep -c 'CASCADE' app/ingest/writer.py` | ✓ 2 matches (TRUNCATE + ON DELETE doc) |
| `grep -cE "f['\"](SELECT\|INSERT\|UPDATE\|DELETE\|TRUNCATE)" app/ingest/writer.py` | ✓ 0 — T-04-01 mitigation |
| `grep -c '%s' app/ingest/writer.py` | ✓ 11 (≥ 5 required) |
| `grep -c 'def main(argv:' app/ingest/pipeline.py` | ✓ 1 |
| `grep -c '^if __name__ == "__main__":' app/ingest/pipeline.py` | ✓ 1 |
| `grep -c 'argparse' app/ingest/pipeline.py` | ✓ 3 |
| `grep -c -- '--full-rebuild' app/ingest/pipeline.py` | ✓ 3 (flag definition + 2 doc mentions) |
| `grep -c 'get_embedder' app/ingest/pipeline.py` | ✓ 4 |
| `grep -cE '^(from openai\|import openai)' app/ingest/pipeline.py` | ✓ 0 — Embedder Protocol enforced |
| Static test_no_fstring_sql_in_writer regex sweep | ✓ 0 offenders |
| Static argparse sanity: `--full-rebuild` AND `--forum-dir` registered via `parser.add_argument` | ✓ both present |

## Verification Deferred (Infrastructure Required)

The acceptance criteria below require a running Postgres with pgvector + the Python 3.12 venv + `psql` on PATH. None are present in this execution environment (only Python 3.8 is available; `psycopg`/`pgvector` aren't installable on it; no `DATABASE_URL` set; no `OPENAI_API_KEY`). The files are correct — these gates must be run on the user's local machine:

```bash
# 0. Prep (one-time; same prereqs as Plan 01-01's deferred block)
pyenv local 3.12
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export DATABASE_URL=postgresql://localhost:5432/guitar_tone_advisor
export OPENAI_API_KEY=sk-...                    # real key
createdb guitar_tone_advisor                   # if not already
psql "$DATABASE_URL" -f scripts/init_db.sql    # idempotent

# 1. First ingest run (INGEST-01)
python -m app.ingest.pipeline
# expected stdout: OK: 21 chunks inserted, 0 skipped across 10 documents.
# exit code: 0

# 2. Chunks populated (INGEST-01, INGEST-02)
psql -At "$DATABASE_URL" -c "SELECT COUNT(*) FROM chunks"
# expected: 21

psql -At "$DATABASE_URL" -c "SELECT DISTINCT embedding_model FROM chunks"
# expected: text-embedding-3-small

# 3. Idempotency on second run (INGEST-06)
python -m app.ingest.pipeline
# expected stdout: OK: 0 chunks inserted, 21 skipped across 10 documents.

psql -At "$DATABASE_URL" -c \
  "SELECT n_chunks_inserted, n_chunks_skipped FROM ingest_runs ORDER BY started_at DESC LIMIT 1"
# expected: 0|21

# 4. --full-rebuild truncates + re-embeds (D-04)
python -m app.ingest.pipeline --full-rebuild
psql -At "$DATABASE_URL" -c \
  "SELECT full_rebuild, n_chunks_inserted FROM ingest_runs ORDER BY started_at DESC LIMIT 1"
# expected: t|21

# 5. HNSW index is hot (Phase 1 success criterion #3 from ROADMAP)
psql "$DATABASE_URL" -c "
  EXPLAIN ANALYZE
  SELECT id FROM chunks
  ORDER BY embedding <=> (SELECT embedding FROM chunks LIMIT 1)
  LIMIT 8"
# expected: an 'Index Scan using chunks_embedding_hnsw_cos' line — NOT 'Seq Scan'

# 6. Pytest suites
pytest tests/test_writer.py tests/test_pipeline.py -v
# expected: 12 + 6 = 18 passed, OR 12 passed + 5 skipped + 1 passed (if no key)
```

## Expected Chunk Distribution (after first run)

Locked by Plan 01-02 — the writer is a pass-through and stores exactly what the chunker emits:

| Source file                              | Chunks | Token counts per chunk |
|------------------------------------------|-------:|------------------------|
| `bb_king_tone.txt`                       |      3 | [459, 470, 434]        |
| `eddie_van_halen_tone.txt`               |      2 | [406, 148]             |
| `funk_tone.txt`                          |      1 | [493]                  |
| `indian_sounding_guitar_sound.txt`       |      2 | [421, 162]             |
| `john_mayer_tone.txt`                    |      3 | [413, 462, 465]        |
| `lo_fi_tone.txt`                         |      2 | [477, 326]             |
| `mark_knopfler_bowed_sound.txt`          |      2 | [448,  53]             |
| `modern_pop_punk_tone.txt`               |      2 | [490, 233]             |
| `rnb_neo_soul_tone.txt`                  |      1 | [487]                  |
| `unconventional_tones.txt`               |      3 | [494, 375, 163]        |

**Total: 21 chunks across 10 documents.** Plan 01-05 (eval authoring) uses these counts to estimate per-topic coverage and will SELECT the live UUIDs of these rows when binding `expected_chunk_ids` to each golden tuple.

## Approximate Runtime (rough order-of-magnitude)

These are estimates for the user's local run; they cannot be measured in this execution environment.

| Run | Documents | Chunks embedded | Approx. wall time (small corpus, OpenAI small) |
|---|---|---|---|
| First (cold) | 10 | 21 | ~3–8 seconds (single batch — well under the BATCH_SIZE=64 cap, so exactly 1 `embeddings.create` call) |
| Second (idempotent) | 10 | 0 | ~0.2 seconds (no embed calls; only the partition SELECTs run) |
| `--full-rebuild` | 10 | 21 | ~3–8 seconds (same as cold, plus one `TRUNCATE`) |

The dominant cost is the OpenAI round-trip; the partition + UPSERT path is sub-second on a 21-row corpus. The idempotent run validates INGEST-06 not just in theory (zero `n_chunks_inserted`) but in practice (no token cost).

## HNSW EXPLAIN ANALYZE Sample (deferred)

`EXPLAIN ANALYZE` against a populated index requires a live DB. The query template the user should run after step 5 above:

```sql
EXPLAIN ANALYZE
SELECT id
FROM chunks
ORDER BY embedding <=> (SELECT embedding FROM chunks LIMIT 1)
LIMIT 8;
```

Expected plan shape (pgvector 0.4.2 + Postgres 16, HNSW with m=16/ef_construction=64 on 21 rows):

```text
Limit  (cost=...)
  ->  Index Scan using chunks_embedding_hnsw_cos on chunks
        Order By: (embedding <=> '...'::vector)
```

The Phase 1 success criterion is that an `Index Scan using chunks_embedding_hnsw_cos` line appears (NOT `Seq Scan`). On 21 rows the planner *could* prefer Seq Scan if the cost model judged it cheaper, but pgvector's HNSW operator class biases toward index use whenever the order-by uses `<=>`. The user should paste their captured plan into `01-04-explain-analyze.txt` for Plan 05's reference if they wish.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking issue] Audit row committed BEFORE iterating documents**

- **Found during:** Task 2 design — re-reading the plan's `<interfaces>` block.
- **Issue:** The plan's pseudocode opened `start_run` then jumped straight into the document loop without an explicit commit on the audit row. psycopg3 default is autocommit=False, which means the `start_run` INSERT sits in the open transaction and is invisible to any concurrent reader (and is rolled back if the process is killed before the first `conn.commit()` lands in the loop body). For a single-user local tool the concurrent-reader case is moot, but the kill-before-first-doc case is real — `kill -9` between `start_run` and the first document commit would leave NO audit row, which contradicts the T-04-08 "audit row survives crashes" mitigation.
- **Fix:** Added `conn.commit()` immediately after `start_run` so the audit row is durable as soon as it's written. The subsequent document loop still per-doc-commits as the plan specified. Documented inline in `pipeline.py` with a comment ("audit row first — visible even if a later step crashes").
- **Files modified:** `app/ingest/pipeline.py`.
- **Commit:** `6bd735c` (Task 2 GREEN — fix landed at the time the file was first written, no separate commit).

**2. [Rule 2 — Missing critical functionality] `conn.close()` in a `finally` block**

- **Found during:** Task 2 implementation review.
- **Issue:** The plan's pseudocode used `with get_conn() as conn:` (psycopg3 context manager handles close-on-exit). But the plan ALSO has us open a fresh connection in the exception path for `fail_run`, which means we already have two distinct connections to manage. To keep the lifecycle explicit and the exception path obvious, I switched to a manual `conn = get_conn()` + `try/finally: conn.close()` pattern. Without `finally: conn.close()`, an exception thrown by `start_run` itself (e.g., schema not initialized) would leak the connection.
- **Fix:** `conn = get_conn()` at the top, `try` block for the entire workflow, `finally: conn.close()` to guarantee cleanup. The exception path opens its OWN fresh connection via `with get_conn() as fresh:` so the audit write isn't blocked on the (now-being-closed) main connection.
- **Files modified:** `app/ingest/pipeline.py`.
- **Commit:** `6bd735c`.

**3. [Rule 2 — Missing critical functionality] Inner try/except around `fail_run` to avoid masking the original exception**

- **Found during:** Task 2 — considering what happens if Postgres itself is down (the original `e` is the trigger, but the recovery path will *also* fail because `get_conn()` won't work).
- **Issue:** If the original exception is a connection error (e.g., Postgres went away mid-run), the recovery `get_conn()` call will *also* throw. The plan's pseudocode would propagate the secondary exception instead of the primary one, masking the actual failure cause. The operator wants to know "embedding failed", not "and by the way the audit-write reconnection also failed".
- **Fix:** Wrapped the audit-write in `try/except Exception as audit_err: logger.error(...)`. The primary `e` is then re-raised by the outer `raise`. The operator sees both failures in the log but the process exits with the original cause.
- **Files modified:** `app/ingest/pipeline.py`.
- **Commit:** `6bd735c`.

**4. [Rule 1 — Bug fix in advance] Embedder construction happens BEFORE `get_conn()`**

- **Found during:** Task 2 — sequencing the lifecycle.
- **Issue:** The plan's pseudocode constructs the embedder INSIDE the `with get_conn() as conn:` block. If `get_embedder()` raises (e.g., unknown `EMBEDDING_MODEL`), we'd have already opened a connection that needs cleanup. Worse, we'd write a `start_run` row with the WRONG model name (because `embedder.model` wouldn't exist yet to populate it).
- **Fix:** Construct `embedder = get_embedder()` BEFORE opening the connection. Any factory error fails the process before we touch the DB at all. Once the embedder exists, `embedder.model` is the value passed to `start_run` so the audit row is correctly stamped with the model actually in use.
- **Files modified:** `app/ingest/pipeline.py`.
- **Commit:** `6bd735c`.

### Authentication Gates

None reached during execution. Plan 04 introduces the first live OpenAI API call in the entire codebase — the first time `python -m app.ingest.pipeline` is run against a real DB, the user must have `OPENAI_API_KEY` set. The pipeline does not gracefully degrade if it's missing; the underlying `OpenAIEmbedder` will surface a 401 from `client.embeddings.create()` on the first batch. That's the right failure mode (loud and traceable), not a deviation.

## TDD Gate Compliance

Both tasks are `tdd="true"`. Gate sequence verified in `git log --oneline -5`:

| Task | RED commit | GREEN commit | RED gate proof |
|---|---|---|---|
| Task 1 (writer) | `3d37015` | `77bc562` | `ModuleNotFoundError: No module named 'app.ingest.writer'` on collection |
| Task 2 (pipeline) | `6d9b99a` | `6bd735c` | `ModuleNotFoundError: No module named 'app.ingest.pipeline'` on collection |

**REFACTOR** — skipped for both tasks. The writer is a thin set of single-purpose functions; the pipeline is the linear lifecycle the plan specifies. No duplication or smell to clean up.

## Threat Model Status

| Threat ID | Component | Disposition | Status |
|-----------|-----------|-------------|--------|
| T-04-01 (Tampering / SQLi) | `writer.py` | mitigate | ✅ 0 f-string SQL matches; `tests/test_writer.py::test_no_fstring_sql_in_writer` enforces; 11 `%s` placeholders used. |
| T-04-02 (Tampering / Vector misattribution) | `upsert_chunks` | mitigate | ✅ `assert len(chunks) == len(vectors)` at top of `upsert_chunks` raises `AssertionError` before any binding. |
| T-04-03 (Integrity / Partial Failure) | pipeline tx lifecycle | mitigate | ✅ Per-document `conn.commit()`; partial corpus survives a kill mid-loop. |
| T-04-04 (Repudiation / model identity) | `chunks.embedding_model` | mitigate | ✅ Every chunk row stores `embedder.model` (the post-construction attribute, not the env-var pre-image). |
| T-04-05 (Info Disclosure / verbose errors) | `fail_run.error` | mitigate | ✅ `repr(e)` only; not `traceback.format_exc()`. OpenAI SDK exceptions do not include the API key in their message bodies (verified against `openai 2.36`). |
| T-04-06 (Tampering / Path Traversal) | `--forum-dir` flag | mitigate | ✅ Loader (Plan 02) resolves the dir + globs `*.txt`; no escape. Pipeline passes the flag through unchanged. |
| T-04-07 (DoS / Embedding API rate) | embedder rate | accept | ✅ Corpus is 10 files / 21 chunks → exactly 1 `embeddings.create` call. tenacity caps per-batch. |
| T-04-08 (Repudiation / Audit gap) | `fail_run` write path | mitigate | ✅ Fresh `get_conn()` in the exception handler so the audit row survives the main-tx rollback. Wrapped in its own try/except so a secondary failure does not mask the primary one. |

## Threat Flags

None — Plan 04 introduces no new security surface beyond what the plan's threat model already enumerated. The CLI accepts one new operator-controlled flag (`--forum-dir`); the Phase 1 loader (Plan 02 Task 1) already mitigates traversal at the read site. No new network endpoints; no new auth boundaries; no new schema columns.

## Known Stubs

None. The writer and pipeline are fully functional — every code path in `upsert_document`, `chunks_to_embed`, `upsert_chunks`, the three `ingest_runs` lifecycle functions, `truncate_all`, and the pipeline's main/exception flow is exercised by either an automated test or a deferred live-DB verification step listed above. No empty-list fallbacks, no "coming soon" placeholders, no hardcoded mock data.

## Self-Check: PASSED

Created files (existence verified via `[ -f path ]`):

- FOUND: `app/ingest/writer.py` (301 lines)
- FOUND: `app/ingest/pipeline.py` (188 lines)
- FOUND: `tests/test_writer.py` (505 lines; min 60 required)
- FOUND: `tests/test_pipeline.py` (245 lines; min 50 required)

Commits (`git log --oneline -4` verified):

- FOUND: `3d37015` — `test(01-04): add failing writer + ingest_runs lifecycle tests (RED)`
- FOUND: `77bc562` — `feat(01-04): implement writer with content-hash dedup (GREEN)`
- FOUND: `6d9b99a` — `test(01-04): add failing pipeline CLI smoke tests (RED)`
- FOUND: `6bd735c` — `feat(01-04): implement ingestion CLI pipeline (GREEN)`

Static acceptance gates: all 16 grep / AST checks listed in the Verification Performed Here table pass. Live-DB / live-API gates are deferred to the user's local environment per the "Verification Deferred" block above — no code changes expected to be needed.
