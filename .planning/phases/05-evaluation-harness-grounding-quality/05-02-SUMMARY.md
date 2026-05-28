---
phase: 05-evaluation-harness-grounding-quality
plan: "02"
subsystem: eval
tags: [eval, refusal, generation, smoke-tests, tdd, grounding]
dependency_graph:
  requires:
    - app/generation/generator.py
    - app/generation/prompt.py
    - app/retrieval/base.py
    - app/session.py
  provides:
    - tests/test_eval_refusal.py
  affects: []
tech_stack:
  added: []
  patterns:
    - _FakeAnthropicClient/_FakeAnthropicStream pattern (verbatim from test_generation.py)
    - asyncio.run() in sync test body (no pytest-asyncio — Pitfall 3 avoidance)
    - stream_response() direct call pattern (never via HTTP endpoint — Pitfall 5 avoidance)
    - ANTHROPIC_API_KEY fixture-based skip for live integration gating
    - module-level _KNOB_RE + REFUSAL_PHRASES constants for assertion machinery
key_files:
  created:
    - tests/test_eval_refusal.py
  modified: []
decisions:
  - "Tests call stream_response() directly via asyncio.run(_collect(...)). Never routed through TestClient/HTTP to avoid the raise_server_exceptions=False silent-swallow pitfall (Pitfall 5)."
  - "_FABRICATED_EVH_RESPONSE used in test 1 to confirm the negative-assertion machinery (not-refusal + _KNOB_RE matches) works before testing real paths in tests 2 and 3."
  - "Task 2 required no file changes — the 3 offline tests passed GREEN against the existing generation layer immediately after Task 1 write."
  - "integration mark warning (PytestUnknownMarkWarning) is cosmetic — pytest still skips the test correctly via the anthropic_key fixture. No markers.ini update needed."
metrics:
  duration_minutes: 2
  completed_date: "2026-05-28"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 0
---

# Phase 5 Plan 02: Refusal Contract Smoke Tests Summary

**One-liner:** 4 refusal smoke tests (3 offline unit + 1 live integration) asserting GEN-06's empty-context and adversarial-mismatch refusal contract via direct stream_response() calls.

## What Was Built

### tests/test_eval_refusal.py

Refusal contract smoke test module with 4 tests:

| Test | Type | Coverage |
|------|------|----------|
| test_empty_context_refusal_assertion | offline unit | Proves negative-assertion machinery: fabricated response fails refusal-phrase check and trips _KNOB_RE |
| test_empty_context_produces_refusal | offline unit | Empty sources_with_ids + faked refusal token → refusal phrase asserted |
| test_adversarial_mismatch_no_knobs | offline unit | Lo-fi chunk as sources + faked refusal → refusal phrase asserted AND _KNOB_RE.findall == [] |
| test_live_empty_context_produces_refusal | live integration | Real AsyncAnthropic client, empty context → real model must produce refusal phrase |

**Module-level constants:**
- `REFUSAL_PHRASES = ("I don't have material", "the closest I have")` — exact phrases from SYSTEM_PROMPT_TEXT rule 2
- `_KNOB_RE = re.compile(r"[A-Za-z][A-Za-z\s]{0,15}[:=]\s*\d+(?:\.\d+)?")` — detects fabricated knob/EQ settings
- `_FABRICATED_EVH_RESPONSE` — pre-canned fabricated answer for negative-path test

**_FakeAnthropicStream / _FakeAnthropicClient / _FakeMessages:** Copied verbatim from test_generation.py lines 61–98. Async context manager, `.messages.stream(**kwargs)` returns pre-canned token list.

**_collect() async helper:** Drains stream_response() filtering `sse.event is None` + `"text" in payload` — matches generator.py line 97 token shape exactly.

**anthropic_key fixture:** `pytest.skip("ANTHROPIC_API_KEY not set ...")` when env var absent.

## Verification Results

```
venv/bin/python -m pytest tests/test_eval_refusal.py --collect-only -q
→ 4 tests collected

venv/bin/python -m pytest tests/test_eval_refusal.py -k "not integration" -q
→ 3 passed, 1 deselected

venv/bin/python -m pytest tests/test_eval_refusal.py -q
→ 3 passed, 1 skipped (integration skipped — ANTHROPIC_API_KEY not set)

venv/bin/python -m pytest tests/ -q
→ 138 passed, 6 skipped (no regressions vs 135-test baseline)

git diff --stat app/generation/
→ (empty — no production code modified)

grep -c "TestClient\|httpx\|/chat" tests/test_eval_refusal.py
→ 0

grep -c "asyncio.run" tests/test_eval_refusal.py
→ 3
```

## Deviations from Plan

None — plan executed exactly as written.

Task 2 was a verification-only task; no file changes were needed since the 3 offline tests passed GREEN against the existing generation layer immediately on first run after Task 1.

## Known Stubs

None. All tests are fully implemented and exercising real production code paths (stream_response, build_system_blocks, build_messages, ChunkResult).

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes introduced.

Threats in scope (per plan):
- T-05-01 (fabricated grounding): mitigated — smoke tests assert refusal phrases for empty + adversarial context and assert no knob-setting pattern leaks; run in every pytest invocation.
- T-05-07 (silent test suppression): mitigated — tests call stream_response() directly via asyncio.run(); never via TestClient with raise_server_exceptions=False. Enforced by acceptance criterion grep (returns 0).

## Self-Check: PASSED

- `tests/test_eval_refusal.py`: FOUND (/Users/yashvinaykumar/Desktop/guitar-tone-advisor/tests/test_eval_refusal.py)
- Task 1 commit 0862758: FOUND
