# Phase 5: Evaluation Harness & Grounding Quality - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-27
**Phase:** 5-Evaluation Harness & Grounding Quality
**Areas discussed:** Retrieval scoring scope, RAGAS approach, Refusal smoke test strategy, runs.jsonl schema + CLI diff

---

## Retrieval Scoring Scope

### Q1: Scoring scope

| Option | Description | Selected |
|--------|-------------|----------|
| Held-out 5 only | Matches HELD_OUT.md contract — unbiased recall@K/MRR | |
| All 22 tuples | Larger sample but non-held-out tuples were visible during Phase 2 tuning | |
| Configurable — --held-out flag | Default held-out only; --all uses all 22 | ✓ |

**User's choice:** Configurable — --held-out flag

---

### Q2: K values for recall@K

| Option | Description | Selected |
|--------|-------------|----------|
| recall@1, recall@5, recall@8 + MRR | Covers deployed K=8, mid-range, and top-1 precision | ✓ |
| recall@K for K in {1, 3, 5, 8, 10} + MRR | More granular but K=10 above current limit | |
| Just recall@8 + MRR | Minimalist — only deployed K | |

**User's choice:** recall@1, recall@5, recall@8 + MRR

---

### Q3: Live DB vs injected deps

| Option | Description | Selected |
|--------|-------------|----------|
| Live DB when CLI; injected deps in unit tests | Mirrors retrieve() pattern | ✓ |
| Always live DB — no injection | Simpler but no unit tests for scorer logic | |

**User's choice:** Live DB when CLI; injected deps in unit tests

---

## RAGAS Approach

### Q1: Library vs custom

| Option | Description | Selected |
|--------|-------------|----------|
| Custom LLM claim decomposer | Uses existing anthropic client; no new deps; consistent with no-framework philosophy | ✓ |
| ragas library | Industry standard but pulls in langchain — banned by CLAUDE.md | |
| Lightweight ragas (faithfulness only) | Still has langchain transitive dep | |

**User's choice:** Custom LLM claim decomposer

---

### Q2: Answer source

| Option | Description | Selected |
|--------|-------------|----------|
| Generate live via Anthropic API | Always fresh; reflects current prompt + model | ✓ |
| Pre-generated answer cache | Cheaper to re-run but staleness risk | |

**User's choice:** Generate live via Anthropic API

---

### Q3: Sample size

| Option | Description | Selected |
|--------|-------------|----------|
| All held-out 5 | Consistent with retrieval scorer; comparable numbers | ✓ |
| Random 3-5 from full 22 | More variety but non-deterministic across runs | |
| Configurable — --n flag | Most flexible but adds interface complexity | |

**User's choice:** All held-out 5

---

## Refusal Smoke Test Strategy

### Q1: Live API vs mock

| Option | Description | Selected |
|--------|-------------|----------|
| Monkeypatched client only | Fast, deterministic, no API cost | |
| Live Anthropic API call | Tests real behavior but flaky/expensive | |
| Both — offline mock + one live integration test | Offline mock in every run; live test skipped unless ANTHROPIC_API_KEY set | ✓ |

**User's choice:** Both — offline mock + one live integration test

---

### Q2: Adversarial case scope

| Option | Description | Selected |
|--------|-------------|----------|
| Include in Plan 2 | ROADMAP explicitly mentions it; cross-topic pairing is testable | ✓ |
| Defer — only empty-context | Simpler but weaker coverage | |

**User's choice:** Include in Plan 2

---

### Q3: Refusal assertion method

| Option | Description | Selected |
|--------|-------------|----------|
| Assert refusal phrases in response text | Checks exact phrases from SYSTEM_PROMPT_TEXT rule 2 | ✓ |
| Assert no [Sn] citations appear | Weaker — model could still fabricate without citing | |
| Assert response length < threshold | Brittle | |

**User's choice:** Assert refusal phrases ("I don't have material" / "the closest I have")

---

## runs.jsonl Schema + CLI Diff

### Q1: Per-run fields

| Option | Description | Selected |
|--------|-------------|----------|
| Timestamp + k + recall@1/5/8 + MRR + scope flag | Captures what was tested + enough context to diagnose differences | ✓ |
| Timestamp + k + metrics only (minimal) | Loses scope/model context | |
| Full config snapshot + metrics | Future-proof but verbose | |

**User's choice:** Timestamp + k + recall@1/5/8 + MRR + scope + embedding_model

---

### Q2: CLI diff output format

| Option | Description | Selected |
|--------|-------------|----------|
| Delta per metric with direction arrow | `recall@8: 0.60 → 0.80 (+0.20 ↑)` per metric | ✓ |
| Just current run numbers | No comparison — simpler | |
| Full table of all runs | Gets noisy fast | |

**User's choice:** Delta per metric with direction arrow

---

## Claude's Discretion

None — all decisions were explicitly made by the user.

## Deferred Ideas

None — discussion stayed within Phase 5 scope.
