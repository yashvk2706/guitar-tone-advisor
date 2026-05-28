---
phase: 5
slug: evaluation-harness-grounding-quality
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-28
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 |
| **Config file** | none — already installed in venv |
| **Quick run command** | `venv/bin/python -m pytest tests/test_eval_retrieval.py tests/test_eval_refusal.py tests/test_eval_ragas.py -q --tb=short` |
| **Full suite command** | `venv/bin/python -m pytest tests/ -q --tb=short` |
| **Estimated runtime** | ~5 seconds (offline tests only) |

---

## Sampling Rate

- **After every task commit:** Run `venv/bin/python -m pytest tests/test_eval_retrieval.py tests/test_eval_refusal.py tests/test_eval_ragas.py -q`
- **After every plan wave:** Run `venv/bin/python -m pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 5-01-01 | 01 | 1 | EVAL-02 | — | No f-string SQL in eval modules | unit | `pytest tests/test_eval_retrieval.py::test_recall_at_k_hit -x` | ❌ W0 | ⬜ pending |
| 5-01-02 | 01 | 1 | EVAL-02 | — | recall_at_k miss returns 0.0 | unit | `pytest tests/test_eval_retrieval.py::test_recall_at_k_miss -x` | ❌ W0 | ⬜ pending |
| 5-01-03 | 01 | 1 | EVAL-02 | — | reciprocal_rank returns 1/rank | unit | `pytest tests/test_eval_retrieval.py::test_mrr_calculation -x` | ❌ W0 | ⬜ pending |
| 5-01-04 | 01 | 1 | EVAL-02 | — | append_run creates and appends | unit | `pytest tests/test_eval_retrieval.py::test_runs_jsonl_append -x` | ❌ W0 | ⬜ pending |
| 5-01-05 | 01 | 1 | EVAL-02 | — | format_diff first-run output | unit | `pytest tests/test_eval_retrieval.py::test_diff_first_run -x` | ❌ W0 | ⬜ pending |
| 5-01-06 | 01 | 1 | EVAL-02 | — | format_diff delta with arrow | unit | `pytest tests/test_eval_retrieval.py::test_diff_with_prior -x` | ❌ W0 | ⬜ pending |
| 5-01-07 | 01 | 1 | EVAL-02 | — | CLI --help wiring | unit | `pytest tests/test_eval_retrieval.py::test_retrieval_cli_help -x` | ❌ W0 | ⬜ pending |
| 5-01-08 | 01 | 1 | EVAL-02 | — | Live scorer runs against real DB | integration | `pytest tests/test_eval_retrieval.py -m integration` | ❌ W0 | ⬜ pending |
| 5-02-01 | 02 | 2 | EVAL-03 | T-05-01 | Fabricated response → assertion fires | unit | `pytest tests/test_eval_refusal.py::test_empty_context_refusal_assertion -x` | ❌ W0 | ⬜ pending |
| 5-02-02 | 02 | 2 | EVAL-03 | T-05-01 | Empty context → refusal phrase | unit | `pytest tests/test_eval_refusal.py::test_empty_context_produces_refusal -x` | ❌ W0 | ⬜ pending |
| 5-02-03 | 02 | 2 | EVAL-03 | T-05-01 | Adversarial mismatch → no knob patterns | unit | `pytest tests/test_eval_refusal.py::test_adversarial_mismatch_no_knobs -x` | ❌ W0 | ⬜ pending |
| 5-02-04 | 02 | 2 | EVAL-03 | T-05-01 | Live: real model with empty context refuses | integration | `pytest tests/test_eval_refusal.py -m integration` | ❌ W0 | ⬜ pending |
| 5-03-01 | 03 | 3 | EVAL-04 | T-05-02 | parse_claims extracts JSON array | unit | `pytest tests/test_eval_ragas.py::test_parse_claims -x` | ❌ W0 | ⬜ pending |
| 5-03-02 | 03 | 3 | EVAL-04 | T-05-02 | parse_claims handles fenced JSON | unit | `pytest tests/test_eval_ragas.py::test_parse_claims_fenced -x` | ❌ W0 | ⬜ pending |
| 5-03-03 | 03 | 3 | EVAL-04 | T-05-02 | parse_support returns True/False | unit | `pytest tests/test_eval_ragas.py::test_parse_support -x` | ❌ W0 | ⬜ pending |
| 5-03-04 | 03 | 3 | EVAL-04 | — | faithfulness = supported/total | unit | `pytest tests/test_eval_ragas.py::test_faithfulness_score -x` | ❌ W0 | ⬜ pending |
| 5-03-05 | 03 | 3 | EVAL-04 | — | CLI --help wiring | unit | `pytest tests/test_eval_ragas.py::test_ragas_cli_help -x` | ❌ W0 | ⬜ pending |
| 5-03-06 | 03 | 3 | EVAL-04 | T-05-03 | No direct openai import in app/eval/ | static | `pytest tests/test_eval_ragas.py::test_no_direct_openai_import -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_eval_retrieval.py` — 8 stubs covering EVAL-02
- [ ] `tests/test_eval_refusal.py` — 4 stubs covering EVAL-03
- [ ] `tests/test_eval_ragas.py` — 6 stubs covering EVAL-04

No new framework install needed — pytest 9.0.3 is already in the venv.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live RAGAS CLI run produces faithfulness score | EVAL-04 | Requires live Anthropic API + DB; each run costs ~10 API calls | Run `venv/bin/python -m app.eval.ragas`; verify `eval/faithfulness_runs.jsonl` is appended and per-query breakdown prints to stdout |
| Live retrieval scorer diff output | EVAL-02 | Requires live DB + OpenAI key | Run `venv/bin/python -m app.eval.retrieval` twice; verify second run shows delta vs first |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
