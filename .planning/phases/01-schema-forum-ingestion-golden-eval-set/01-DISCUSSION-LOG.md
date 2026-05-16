# Phase 1: Schema, Forum Ingestion & Golden Eval Set - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-15
**Phase:** 1-Schema-Forum-Ingestion-Golden-Eval-Set
**Areas discussed:** Forum chunking boundary, Schema initialization, Eval authoring workflow, Python packaging

---

## Forum Chunking Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Paragraph-packing | Greedy accumulate to 300-500 tokens; merge short paragraphs (≤40 words) forward; stable (source_id, chunk_index) IDs; no quoted-reply stripping needed (actual files have none) | ✓ |
| Heuristic post-boundary detection | Regex-detect individual post boundaries, one chunk per short post; unreliable given actual file formats with no consistent delimiter | |

**User's choice:** Paragraph-packing — with the addition that `source_filename` (e.g., `bb_king_tone.txt`) must be included in chunk metadata so the eval authoring script can display which forum topic each chunk came from during EVAL-01 human review.

**Notes:** Agent read the actual `.txt` files and confirmed: no `>` or `[quote]` syntax present, files are 20-71 lines and ~500-1300 tokens total. Paragraph-packing will produce ~2-4 chunks per file (roughly 20-40 total chunks for Phase 1).

---

## Schema Initialization

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone SQL script (`scripts/init_db.sql`) | Run once via `psql -f scripts/init_db.sql`; idempotent with IF NOT EXISTS guards; explicit and inspectable | ✓ |
| Auto-DDL in pipeline | Pipeline checks/creates tables on first run; self-bootstrapping but mixes DDL into ingestion code; `CREATE EXTENSION` may need superuser different from app user | |

**User's choice:** Standalone SQL script.

**Notes:** Script creates both `vector` and `pg_trgm` extensions (pg_trgm pre-installed for Phase 3 hybrid search headroom per ROADMAP.md Plan 1), all three tables (documents, chunks, ingest_runs), and the HNSW index with m=16, ef_construction=64.

---

## Eval Authoring Workflow

| Option | Description | Selected |
|--------|-------------|----------|
| Scripted helper (`app/eval/author.py`) | Presents top-K retrieval results per draft query, human accepts/rejects chunks, writes JSONL with live chunk UUIDs from DB; fixed enum for expected_themes; 15/5 train/held-out split | ✓ |
| Fully manual (psql + hand-write JSONL) | Zero new code; fragile UUID transcription across 20+ tuples; silent errors would corrupt Phase 5 MRR scores | |

**User's choice:** Scripted helper — with the specific held-out split of 15 training / 5 held-out as suggested, with held-out queries committed to `eval/HELD_OUT.md` with a timestamp before any Phase 2 retrieval tuning begins.

**Notes:** `expected_themes` uses fixed enum: `["amp_settings", "pedal_choice", "signal_chain", "pickup_tone", "studio_vs_live"]`. JSONL schema: `{"query": str, "expected_chunk_ids": [str], "expected_themes": [str], "held_out": bool}`. `eval/HELD_OUT.md` ordering constraint is hard (pre-Phase-2 commit required).

---

## Python Packaging

| Option | Description | Selected |
|--------|-------------|----------|
| `requirements.txt` only | Simple pinned deps, `python -m app.ingest.pipeline` works from project root; Python 3.12 pinned via `.python-version` | ✓ |
| `pyproject.toml` + editable install | Works from any directory, named entry points; overhead unnecessary for local single-user tool | |

**User's choice:** `requirements.txt` only.

**Notes:** Optional `requirements-dev.txt` for pytest/ruff. Research STACK.md already provides the full pinned `requirements.txt` content as a starting point.

---

## Claude's Discretion

- HNSW index parameters (`m=16, ef_construction=64`) — use research defaults.
- Batch size for OpenAI embedding API calls — 64 per batch.
- `ingest_runs` status transition logic — straightforward implementation.

## Deferred Ideas

None — discussion stayed within phase scope.
