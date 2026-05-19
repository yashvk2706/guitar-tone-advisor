---
phase: 2
slug: retrieval-layer-gear-aliases
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-18
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.4.0 (`/opt/anaconda3/bin/pytest`) |
| **Config file** | none — no pyproject.toml, pytest.ini, or conftest.py found |
| **Quick run command** | `pytest tests/test_retrieval.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds (offline unit tests); live-DB tests auto-skip if Postgres unreachable |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_retrieval.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green (offline tests pass; live-DB tests skip gracefully if no Postgres)
- **Max feedback latency:** ~5 seconds (offline tests only)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | INGEST-07 | — | No eval/exec in alias expansion | unit | `pytest tests/test_retrieval.py::test_aliases_json_loads -x` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | INGEST-07 | — | Word-boundary match only | unit | `pytest tests/test_retrieval.py::test_expand_shortform -x` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | INGEST-07 | — | Word-boundary match only | unit | `pytest tests/test_retrieval.py::test_expand_canonical -x` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 2 | RETR-01 | T-02-01 | %s placeholders; no f-string SQL | unit (injected) | `pytest tests/test_retrieval.py::test_retrieve_fewer_than_k -x` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 2 | RETR-01 | — | Empty result on empty DB | unit (injected) | `pytest tests/test_retrieval.py::test_retrieve_empty_db -x` | ❌ W0 | ⬜ pending |
| 02-02-03 | 02 | 2 | RETR-01 | — | retrieve() returns list[ChunkResult] | integration | `pytest tests/test_retrieval.py::test_retrieve_returns_chunk_results -x` | ❌ W0 | ⬜ pending |
| 02-02-04 | 02 | 2 | RETR-02 | — | Shortform/canonical retrieval parity | integration | `pytest tests/test_retrieval.py::test_alias_retrieval_parity -x` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 3 | RETR-03 | — | Typed fields; no dict return | unit | `pytest tests/test_retrieval.py::test_chunk_result_fields -x` | ❌ W0 | ⬜ pending |
| 02-03-02 | 03 | 3 | RETR-03 | — | Frozen dataclass (immutable) | unit | `pytest tests/test_retrieval.py::test_chunk_result_is_frozen -x` | ❌ W0 | ⬜ pending |
| 02-guard-01 | 02 | 2 | (guard) | T-02-02 | No direct openai import in retrieval | static scan | `pytest tests/test_retrieval.py::test_no_direct_openai_import -x` | ❌ W0 | ⬜ pending |
| 02-guard-02 | 02 | 2 | (guard) | T-02-01 | No f-string SQL in base.py | static scan | `pytest tests/test_retrieval.py::test_no_fstring_sql -x` | ❌ W0 | ⬜ pending |
| 02-guard-03 | 02 | 2 | (guard) | — | register_vector called by get_conn not retrieve | code inspection | `pytest tests/test_retrieval.py::test_register_vector_not_in_retrieve -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_retrieval.py` — all Phase 2 retrieval and alias tests (does not exist yet; must be created before implementation begins)
- [ ] `data/gear_aliases.json` — static alias file with 14 corpus-verified pairs (does not exist yet)
- [ ] `app/retrieval/__init__.py` — package init (does not exist yet)
- [ ] `app/retrieval/base.py` — ChunkResult dataclass + retrieve() function (does not exist yet)
- [ ] `app/retrieval/aliases.py` — alias loading + expand_query() (does not exist yet)

*No framework install needed — pytest 7.4.0 already available at `/opt/anaconda3/bin/pytest`*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Spot-check alias retrieval parity (≥3 alias pairs) | INGEST-07 SC2 | Requires live DB + real embeddings + visual comparison of top-K | Run `python -c "from app.retrieval.base import retrieve; print(retrieve('Strat neck pickup clean tone'))"` and compare with `retrieve('Stratocaster neck pickup clean tone')` — top chunk should match |
| EXPLAIN ANALYZE shows HNSW index scan | RETR-01 SC3 | Requires live DB; output is visual | Set `DEBUG=true`, run any retrieve() call, verify output contains `Index Scan using chunks_embedding_hnsw_cos` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
