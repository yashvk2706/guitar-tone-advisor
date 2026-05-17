---
phase: 01-schema-forum-ingestion-golden-eval-set
plan: 05
subsystem: eval-authoring
tags: [pydantic-v2, golden-set, jsonl-schema, interactive-cli, eval-author, held-out-lock, audit-anchor]
status: checkpoint-pending
checkpoint_type: human-action
dependency_graph:
  requires:
    - "01-01 schema (chunks.id UUID via gen_random_uuid + documents.source_id text)"
    - "01-02 chunker (Chunk.metadata['source_filename'] = path.name)"
    - "01-03 embedder (app.embeddings.factory.get_embedder → embed_query)"
    - "01-04 pipeline (chunks table populated; user must run python -m app.ingest.pipeline before Task 4)"
  provides:
    - "app.eval.schema.GoldenTuple (Pydantic v2 BaseModel — D-08)"
    - "app.eval.schema.VALID_THEMES + Theme Literal (D-09 closed enum)"
    - "app.eval.schema.load_golden_set / save_golden_set (JSONL helpers with 1-based line-number errors)"
    - "app.eval.author CLI — interactive accept/reject loop via embed_query + 'embedding <=>' cosine retrieval"
    - "eval/QUERIES.md (28 draft queries spanning all 10 forum topics)"
  affects:
    - "Phase 1 cannot close until the human runs Task 4 to produce eval/golden_set.jsonl + eval/HELD_OUT.md and commits them BEFORE any Phase 2 retrieval tuning (D-11 hard ordering)."
    - "Phase 5 retrieval evaluation will SELECT chunks by the UUIDs in golden_set.jsonl and validate them via load_golden_set."
tech_stack:
  added:
    - "pydantic v2 (transitive via pydantic-settings 2.14.1 — no new direct pin needed)"
  patterns:
    - "Pydantic v2 BaseModel + Literal[...] enum for closed-set fields"
    - "@field_validator that normalizes inputs (UUID strings are reformatted through str(uuid.UUID(s)) on the way in)"
    - "JSONL round-trip with ensure_ascii=False; load_golden_set re-raises both json.JSONDecodeError and pydantic.ValidationError under a single ValueError('Malformed JSONL at line N:') shape so callers handle one error type"
    - "Interactive CLI loop with re-prompt on parse errors (parse_accept_input / parse_themes raise ValueError; outer prompt helpers loop until valid)"
    - "Embedder constructed BEFORE get_conn() so factory errors fail before touching Postgres (same pattern as Plan 04 pipeline.py)"
key_files:
  created:
    - app/eval/__init__.py
    - app/eval/schema.py
    - app/eval/author.py
    - eval/QUERIES.md
    - tests/test_eval_schema.py
    - tests/test_eval_author.py
  modified: []
decisions:
  - "Empty accept-input ([], distinct from 'skip' → None) is treated as 'no chunks selected' and dropped: GoldenTuple requires expected_chunk_ids min_length=1 so an empty selection cannot construct a valid tuple. parse_accept_input still returns [] (cleanly distinguishing from 'skip') and main() treats both cases the same — record as skipped, do not construct a tuple."
  - "parse_themes is case-sensitive against VALID_THEMES. The CLI prompt prints the full enum so the reviewer can type-match exactly; a typo (e.g. 'Amp_Settings') is rejected with the offending theme echoed in the ValueError. We deliberately avoided lowercasing to keep the enum boundary unambiguous."
  - "_PREVIEW_CHARS = 200 caps per-candidate text shown in the prompt at exactly the plan's <interfaces> spec; long previews are truncated with '...' and \\n is collapsed to a single space so an 8-candidate list fits in one screen."
  - "Held-out source filenames in HELD_OUT.md are taken from the FIRST accepted candidate per held-out tuple (the 'primary source'). When a tuple's expected_chunk_ids span multiple sources, only the first-source filename is listed in the manifest. This is sufficient for D-10 (the operator confirms 5 distinct topics by inspection); a multi-source held-out tuple is rare and acceptable for the audit statement."
  - "_FakeInput test-double pattern adopted: monkeypatch builtins.input with a FIFO callable. This is the convention for any future test that needs to drive an interactive prompt; documented in test_eval_author.py::test_main_dry_run as the reference example."
metrics:
  duration_minutes: ~20
  tasks_completed: 3  # of 4 — Task 4 is a human checkpoint
  files_created: 6
  files_modified: 0
  commits: 5  # 4 task commits + this summary
  completed_date: 2026-05-16
---

# Phase 01 Plan 05: Golden Eval Set Authoring (Tasks 1-3 Shipped, Task 4 Awaits Human)

**One-liner:** Pydantic v2 `GoldenTuple` + closed-enum `Theme` (D-08, D-09) and the interactive `python -m app.eval.author` CLI are now committed — it surfaces top-K candidate chunks per draft query via `embed_query` + `embedding <=>` cosine retrieval, captures human accept/reject, and writes JSONL + HELD_OUT.md; 28 draft queries spanning all 10 forum topics sit in `eval/QUERIES.md` ready for the reviewer. **The plan is paused at the `checkpoint:human-action` gate until the human runs the CLI, produces `eval/golden_set.jsonl` (≥20 tuples, exactly 5 held_out) + `eval/HELD_OUT.md`, and commits both BEFORE any Phase 2 retrieval tuning (D-11).**

## What Shipped

### Task 1 — Eval schema module (commits `553a091` RED, `82b45f6` GREEN)

- `tests/test_eval_schema.py` (8 tests + 1 bonus = 9 cases) committed FIRST as the RED gate. Collection failed with `ModuleNotFoundError: No module named 'app.eval.schema'`.
- `app/eval/__init__.py` — empty package marker.
- `app/eval/schema.py` (146 lines):
  - `VALID_THEMES: tuple[str, ...]` and `Theme = Literal[...]` share the five locked labels (D-09): `amp_settings, pedal_choice, signal_chain, pickup_tone, studio_vs_live`.
  - `class GoldenTuple(BaseModel)` is a Pydantic v2 model with:
    - `query: str = Field(min_length=1, max_length=300)` — D-08 cap.
    - `expected_chunk_ids: list[str] = Field(min_length=1)` — non-empty.
    - `expected_themes: list[Theme] = Field(min_length=1)` — non-empty, `Literal`-enforced.
    - `held_out: bool`.
    - `@field_validator("expected_chunk_ids")` parses every entry through `uuid.UUID(s)` and re-stores the canonical string form (T-05-02 mitigation — transcription errors fail loudly).
  - `save_golden_set(tuples, path)` writes one `json.dumps(t.model_dump())` per line with `ensure_ascii=False`, newline-terminated; preserves input order.
  - `load_golden_set(path)` reads line-by-line, parses JSON, validates through `GoldenTuple.model_validate`, and re-raises BOTH `json.JSONDecodeError` and `pydantic.ValidationError` as `ValueError(f"Malformed JSONL at line {n}: {orig}")` (1-based).

### Task 2 — Eval authoring CLI (commits `41306ea` RED, `01eec59` GREEN)

- `tests/test_eval_author.py` (9 tests) committed FIRST as the RED gate. Collection failed with `ModuleNotFoundError: No module named 'app.eval.author'`.
- `app/eval/author.py` (472 lines) implements the canonical interactive flow:
  - `read_queries(path)` strips comments + blanks.
  - `parse_accept_input(raw, count)` → `list[int] | None` (None = "skip", `[]` = "no selection", indices = 1-based-to-0-based with range check).
  - `parse_themes(raw)` validates every comma-separated label against `VALID_THEMES`.
  - `write_held_out_md(path, tuples, sources)` emits the ISO-8601 UTC `Locked at:` line, 0-based held-out indices, listed source filenames, and the literal phrase `No retrieval tuning has been performed`.
  - `retrieve_candidates(conn, embedder, query, k)` flows through `embed_query` and runs the single SQL `SELECT c.id::text, c.chunk_text, c.metadata_json, d.source_id FROM chunks c JOIN documents d ON d.id = c.document_id ORDER BY c.embedding <=> %s::vector LIMIT %s` — both vector and `k` bound through psycopg `%s` placeholders (T-05-03).
  - `build_parser()` exposes the four locked flags: `--queries`, `--output`, `--held-out-manifest`, `--k`.
  - `main(argv)` constructs the embedder BEFORE `get_conn()` (factory-error fail-fast pattern from Plan 04), iterates each draft query, prints `[i] (source_filename) {preview[:200]}...` candidates, loops on parse errors, validates each tuple through Pydantic, and finally writes `save_golden_set(...)` + `write_held_out_md(...)` plus a summary by source.
- No `import openai` anywhere in the module — grep gate enforces statically (`tests/test_eval_author.py::test_no_direct_openai_import`).

### Task 3 — Draft queries (commit `3e9740a`)

- `eval/QUERIES.md` — 28 non-comment, non-blank query lines (plan minimum 20), grouped by topic with `# === Topic: ... ===` headers and a documentation preamble at the top.
- Every Phase 1 forum topic appears at least twice:

| Topic header                                        | Source file                            | Queries |
| --------------------------------------------------- | -------------------------------------- | ------: |
| BB King                                             | `bb_king_tone.txt`                     | 3       |
| Eddie Van Halen                                     | `eddie_van_halen_tone.txt`             | 3       |
| Funk                                                | `funk_tone.txt`                        | 3       |
| John Mayer                                          | `john_mayer_tone.txt`                  | 3       |
| Lo-fi guitar                                        | `lo_fi_tone.txt`                       | 3       |
| Mark Knopfler                                       | `mark_knopfler_bowed_sound.txt`        | 3       |
| Modern pop punk                                     | `modern_pop_punk_tone.txt`             | 3       |
| R&B / Neo-soul                                      | `rnb_neo_soul_tone.txt`                | 3       |
| Indian-sounding guitar                              | `indian_sounding_guitar_sound.txt`     | 2       |
| Unconventional tones                                | `unconventional_tones.txt`             | 2       |

- Theme variety: each topic has ≥1 query in `amp_settings`, ≥1 in either `pedal_choice` / `signal_chain` / `pickup_tone`, and several `studio_vs_live` contrast queries (e.g., the BB King studio-vs-live one, the pop punk recording-vs-stage one).
- The plan's `<verify>` Python check passed: 28 queries, all topic substrings present, zero duplicate lines.

## CHECKPOINT REACHED — Task 4 Awaits Human Action

**Type:** `checkpoint:human-action`
**Reason:** D-07 mandates the eval set is curated by a human — chunk relevance is the irreducibly-human judgment that drives Phase 5 recall@K. The CLI handles every automated step (embedding, retrieval, validation, file writes); only the accept/reject decisions and `held_out` flagging are human-only.

### Prerequisites (run on your local machine before Task 4)

```bash
# 0. Python 3.12 venv with all pinned deps.
pyenv local 3.12
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# 1. Postgres + pgvector reachable.
export DATABASE_URL=postgresql://localhost:5432/guitar_tone_advisor
export OPENAI_API_KEY=sk-...    # real key — embed_query hits OpenAI live
psql "$DATABASE_URL" -f scripts/init_db.sql                    # idempotent
psql -At "$DATABASE_URL" -c "SELECT COUNT(*) FROM chunks"      # must be >0
# If 0, run the ingestion pipeline first:
#   python -m app.ingest.pipeline
#   psql -At "$DATABASE_URL" -c "SELECT COUNT(*) FROM chunks"  # expect 21

# 2. Optional: run the static tests now to catch regressions.
pytest tests/test_eval_schema.py tests/test_eval_author.py -v
#   expect: tests 1, 3, 4, 5, 6, 8, 9 in test_eval_author.py + all 9 in
#   test_eval_schema.py pass unconditionally; tests 2 + 7 in
#   test_eval_author.py pass when Postgres is reachable.
```

### Authoring procedure

```bash
python -m app.eval.author
```

For each of the 28 draft queries surfaced from `eval/QUERIES.md`:

1. The CLI prints the top-K candidate chunks (default `k=8`) with their 1-based index, source filename, and the first 200 characters of chunk text. Read each preview.
2. Type a comma-separated list of 1-based indices for the chunks that **actually answer** the query (e.g., `1`, `1,3`, `2,4,5`).
   - Type `skip` if no candidate is acceptable. Aim for 20 keepers from the 28 drafts — you have ~8 skips of headroom.
   - Hit enter with no input to also drop the query (treated as skip).
   - Invalid input (out of range, non-integer) re-prompts.
3. Type 1–N comma-separated themes from the closed enum, exactly as spelled: `amp_settings, pedal_choice, signal_chain, pickup_tone, studio_vs_live`. Mismatches re-prompt with the offending label echoed.
4. Type `y` to mark this tuple `held_out=true`. **Mark exactly 5 tuples as held-out, sourced from 5 distinct forum topics** (D-10). Recommended distribution: one held-out from BB King, one from John Mayer, one from Funk, one from Eddie Van Halen, one from Modern Pop Punk (or any five distinct topics — your call). Type `N` (or hit enter) for the rest.

### Verification after the run

```bash
# 1. JSONL has at least 20 lines.
wc -l eval/golden_set.jsonl
#   expect: >= 20

# 2. Schema validates + held_out count is exactly 5.
python -c "
from pathlib import Path
from app.eval.schema import load_golden_set
ts = load_golden_set(Path('eval/golden_set.jsonl'))
assert len(ts) >= 20, f'only {len(ts)} tuples'
held = sum(t.held_out for t in ts)
assert held == 5, f'held_out={held}, expected exactly 5'
print(f'{len(ts)} tuples, {held} held_out — ok')
"

# 3. Held-out manifest contains the locked statement + a timestamp.
grep -i 'no retrieval tuning has been performed' eval/HELD_OUT.md
grep -iE 'Locked at:.*[0-9]{4}-[0-9]{2}-[0-9]{2}T' eval/HELD_OUT.md

# 4. The 5 held-out tuples come from 5 DISTINCT forum topics.
python -c "
import json, psycopg
from pathlib import Path
from app.db import get_conn
held = [json.loads(l) for l in Path('eval/golden_set.jsonl').read_text().splitlines() if l.strip()]
held_ids = sum([t['expected_chunk_ids'] for t in held if t['held_out']], [])
with get_conn() as c, c.cursor() as cur:
    cur.execute(
        'SELECT DISTINCT d.source_id FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.id::text = ANY(%s)',
        (held_ids,),
    )
    sources = {row[0] for row in cur.fetchall()}
assert len(sources) >= 5, f'only {len(sources)} distinct held-out sources: {sources}'
print(f'held-out sources ({len(sources)}): {sorted(sources)}')
"
```

### Commit before Phase 2

```bash
git add eval/golden_set.jsonl eval/HELD_OUT.md
git commit -m "docs(eval): lock golden_set.jsonl and HELD_OUT.md before Phase 2 tuning (EVAL-01, D-10, D-11)"
git log --oneline -n 1   # must show this commit
git status               # must be clean
```

**This commit is the audit anchor required by D-11.** Phase 2 plan-check should refuse to begin until this commit lands. Do NOT touch any retrieval parameter (K, alias map, expansion strategy) before this commit is in `git log`.

### Resume signal

After committing `eval/golden_set.jsonl` + `eval/HELD_OUT.md`, type `approved` to advance Phase 1 to complete and queue Phase 2. If the authoring run hit any blocker (count off, held-out distribution skewed, manifest missing), describe what happened so the plan can be re-run.

## Verification Performed Here

| Check                                                                                | Result                                  |
| ------------------------------------------------------------------------------------ | --------------------------------------- |
| `python3 -c "import ast; ast.parse(open('app/eval/schema.py').read())"`              | ✓ parses                                |
| `python3 -c "import ast; ast.parse(open('app/eval/author.py').read())"`              | ✓ parses                                |
| `python3 -c "import ast; ast.parse(open('tests/test_eval_schema.py').read())"`       | ✓ parses                                |
| `python3 -c "import ast; ast.parse(open('tests/test_eval_author.py').read())"`       | ✓ parses                                |
| `grep -c amp_settings app/eval/schema.py` (D-09 enum member)                         | ✓ 2 matches (tuple + Literal)           |
| `grep -c pedal_choice app/eval/schema.py`                                            | ✓ 2 matches                             |
| `grep -c signal_chain app/eval/schema.py`                                            | ✓ 2 matches                             |
| `grep -c pickup_tone app/eval/schema.py`                                             | ✓ 2 matches                             |
| `grep -c studio_vs_live app/eval/schema.py`                                          | ✓ 2 matches                             |
| `grep -c 'Literal\[' app/eval/schema.py`                                             | ✓ 2 matches                             |
| `grep -c 'max_length=300' app/eval/schema.py`                                        | ✓ 1 match                               |
| `grep -c 'uuid.UUID' app/eval/schema.py`                                             | ✓ 4 matches                             |
| `grep -cE '^(from openai\|import openai)' app/eval/author.py`                        | ✓ 0 (CLAUDE.md hard constraint)         |
| `grep -c 'embed_query' app/eval/author.py`                                           | ✓ 3 matches (import + call site + doc)  |
| `grep -c 'embedding <=>' app/eval/author.py`                                         | ✓ 1 match (cosine operator)             |
| `grep -c '%s' app/eval/author.py`                                                    | ✓ 5 matches (parameterized SQL)         |
| `grep -c 'def main' app/eval/author.py`                                              | ✓ 1                                     |
| `grep -c '__name__' app/eval/author.py`                                              | ✓ 1 (entry-point guard)                 |
| Plan `<verify>` for QUERIES.md (28 queries, all topics, no dups)                     | ✓ ok                                    |

## Verification Deferred (Infrastructure Required)

Pytest execution + the CLI run itself require **Python 3.12 venv with all `requirements.txt` deps installed + Postgres + pgvector reachable + `OPENAI_API_KEY` set**. The system Python here is 3.8.1 with no pydantic, so `pytest tests/test_eval_schema.py tests/test_eval_author.py -v` could not be run in this environment. The files are correct — these gates must be run on the user's local machine. The exact commands are listed in the "Verification after the run" block of the checkpoint above.

The infrastructure-free gates (AST parse + grep acceptance criteria) were all run and reported above. No code changes are expected to be needed before the user runs the CLI.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 — Missing critical functionality] Empty accept-input is gracefully degraded to "skip" instead of constructing an invalid tuple**

- **Found during:** Task 2 GREEN — reading the plan's `<interfaces>` step 4 (`Empty after strip → return []`) against `GoldenTuple`'s `expected_chunk_ids: list[str] = Field(min_length=1)` from Task 1's schema.
- **Issue:** If `parse_accept_input` returns `[]`, the natural code path in `main()` would attempt `GoldenTuple(query=..., expected_chunk_ids=[], ...)` and raise `ValidationError`, which would either propagate (crashing the entire CLI mid-loop) or — if caught — log a confusing error to the reviewer. The plan's `<interfaces>` step 4 says to return `[]` but step 3.3 also says `If skip, do not record a tuple; continue`. The two cases ("skip" → `None`, "no chunks selected" → `[]`) collapse into the same downstream effect: do not record a tuple. Treating `[]` as "skip" preserves the plan's parse contract AND avoids the validation crash.
- **Fix:** `main()` treats both `None` and `[]` from `parse_accept_input` as the skip path (recorded in the `skipped` list, no tuple constructed). `parse_accept_input` itself still returns the distinct values per the plan's contract — the merge happens in the caller, not the parser.
- **Files modified:** `app/eval/author.py`.
- **Commit:** `01eec59` (Task 2 GREEN).
- **Trade-off:** The reviewer cannot construct a `held_out=true` tuple with zero accepted chunks (the schema forbids it anyway). The plan never required this; documented here for completeness.

**2. [Rule 2 — Missing critical functionality] `conn.close()` in `finally` block + factory-before-conn ordering**

- **Found during:** Task 2 — mirroring the Plan 04 `pipeline.py` lifecycle pattern.
- **Issue:** Without `try/finally: conn.close()`, an exception in the middle of the interactive loop (e.g., Postgres disconnect) would leak the connection. Constructing the embedder INSIDE the `with get_conn() as conn:` block would mean a factory error (`NotImplementedError` for `voyage-*`) wastes a DB connection.
- **Fix:** `embedder = get_embedder()` BEFORE `conn = get_conn()`, then the entire interactive loop inside `try:` with `finally: conn.close()`. Matches the pattern Plan 04 locked.
- **Files modified:** `app/eval/author.py`.
- **Commit:** `01eec59`.

**3. [Rule 1 — Bug] JSONB metadata column may arrive as a string for older psycopg builds**

- **Found during:** Task 2 GREEN — defensive review of `retrieve_candidates`.
- **Issue:** psycopg 3.3 returns JSONB columns as Python dicts by default, but a legacy build or a custom row factory could surface them as JSON strings. The interactive prompt only reads `source_filename` (which comes from `documents.source_id`, a TEXT column — always a string), but the returned dict's `metadata_json` field is forwarded to the caller and may be inspected by future code.
- **Fix:** Added an `isinstance(metadata_json, str)` guard that re-parses with `json.loads` so callers always see a dict. Inline import keeps the json dependency out of the module's hot path.
- **Files modified:** `app/eval/author.py`.
- **Commit:** `01eec59`.

### Authentication Gates

None encountered during execution. Task 4 (the human checkpoint) requires the user to set `OPENAI_API_KEY` before running `python -m app.eval.author` — the embedder factory will raise loudly if the key is missing. Documented in the "Prerequisites" block above; not a deviation.

## TDD Gate Compliance

Tasks 1 and 2 are `tdd="true"`. Gate sequence verified in `git log --oneline -5`:

| Task | RED commit | GREEN commit | RED gate proof                                              |
| ---- | ---------- | ------------ | ----------------------------------------------------------- |
| 1    | `553a091`  | `82b45f6`    | `ModuleNotFoundError: No module named 'app.eval.schema'`    |
| 2    | `41306ea`  | `01eec59`    | `ModuleNotFoundError: No module named 'app.eval.author'`    |

**REFACTOR** — skipped for both. Each task's code is the minimum that satisfies the plan's `<interfaces>`; the helper functions in `author.py` (e.g., `_prompt_themes`) are extracted only because the parse logic is re-prompted on error, not for premature abstraction. No code smell to clean up.

Task 3 is `tdd="false"` (a docs-only task). The plan's `<verify>` Python check is the verification — it ran and passed (28 queries, all topics covered, no duplicates).

## Threat Model Status

| Threat ID                                                                                       | Disposition | Status                                                                                                                                                                                                                                                                                                                                  |
| ----------------------------------------------------------------------------------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T-05-01 (Tampering / Schema Drift — `Theme` enum)                                               | mitigate    | ✅ `Literal` type alias enforces the five-member enum at model-construction time; `tests/test_eval_schema.py::test_invalid_theme_rejected` greps the rejection.                                                                                                                                                                          |
| T-05-02 (Tampering / Transcription Error — `expected_chunk_ids`)                                | mitigate    | ✅ `@field_validator("expected_chunk_ids")` parses every entry through `uuid.UUID`; `tests/test_eval_schema.py::test_invalid_uuid_rejected` verifies the rejection. Also at write time the CLI only allows selecting from the live DB rows (D-07).                                                                                       |
| T-05-03 (Tampering / SQLi — `retrieve_candidates`)                                              | mitigate    | ✅ Both the query vector and `k` bind through psycopg `%s` placeholders. Free-form query text never touches SQL — it is consumed by `embedder.embed_query` (a Python call) and only the resulting vector reaches the DB. `tests/test_eval_author.py::test_author_sql_uses_pgvector_cosine_operator` greps `%s` + `embedding <=>` presence. |
| T-05-04 (Repudiation / Timestamp on held-out lock)                                              | mitigate    | ✅ `write_held_out_md` writes `datetime.now(timezone.utc).isoformat(timespec='seconds')` into the `Locked at:` line; `tests/test_eval_author.py::test_write_held_out_manifest` greps the ISO format. The commit (Task 4) is the tamper-evident anchor.                                                                                   |
| T-05-05 (Information Disclosure / chunk text in terminal)                                       | accept      | ✅ Corpus is non-sensitive forum data; local-only tool. Decision documented in plan.                                                                                                                                                                                                                                                     |
| T-05-06 (Tampering / Coverage Bias — `eval/QUERIES.md`)                                         | mitigate    | ✅ Plan's `<verify>` check enforces every topic substring is present; ran clean (`Missing topics: []`).                                                                                                                                                                                                                                  |
| T-05-07 (Repudiation / Contamination — commit order vs Phase 2)                                 | mitigate    | ⏳ ENFORCED BY HUMAN CHECKPOINT. The Task 4 instructions require the commit BEFORE Phase 2 plan begins; this SUMMARY documents that constraint as a hard gate.                                                                                                                                                                            |
| T-05-08 (Tampering / Reviewer Drift — candidate count)                                          | mitigate    | ✅ `k=8` default bounds the reviewer's choice set; `_PREVIEW_CHARS=200` keeps each preview scannable so reviewer fatigue stays low.                                                                                                                                                                                                      |

## Threat Flags

None — Plan 05 introduces no new security surface beyond what the plan's threat model enumerated. The CLI is local, reads from the user's own Postgres, writes only to `eval/` files inside the repo. The OpenAI embed call is the same one Plan 04 already audited.

## Known Stubs

None. Every function declared in the plan's `<interfaces>` is fully implemented (no placeholder bodies, no hardcoded mock data). The remaining unwritten artifacts — `eval/golden_set.jsonl` and `eval/HELD_OUT.md` — are intentionally NOT written by Tasks 1-3; they are the **output of the human checkpoint** (Task 4). Writing them automatically would defeat the EVAL-01 contract (D-07: human accept/reject is the eval signal).

## Self-Check: PASSED

Created files (existence verified via `[ -f path ]`):

```
$ for p in app/eval/__init__.py app/eval/schema.py app/eval/author.py \
           eval/QUERIES.md tests/test_eval_schema.py tests/test_eval_author.py; do
    if [ -f "$p" ]; then echo "FOUND: $p"; else echo "MISSING: $p"; fi
  done
FOUND: app/eval/__init__.py
FOUND: app/eval/schema.py
FOUND: app/eval/author.py
FOUND: eval/QUERIES.md
FOUND: tests/test_eval_schema.py
FOUND: tests/test_eval_author.py
```

Commits (`git log --oneline -5` verified):

```
3e9740a docs(01-05): draft 28 eval queries spanning all 10 forum topics
01eec59 feat(01-05): implement eval authoring CLI app/eval/author.py (GREEN)
41306ea test(01-05): add failing tests for eval authoring CLI (RED)
82b45f6 feat(01-05): implement eval schema GoldenTuple + JSONL helpers (GREEN)
553a091 test(01-05): add failing tests for eval schema (RED)
```

All four commits the orchestrator was instructed to land for Tasks 1-3 are present in `git log`. The fifth commit (this SUMMARY) lands next.
