---
phase: 3
slug: grounded-generation-minimal-chat-ui
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-19
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.5.0 |
| **Config file** | none — pytest discovery defaults |
| **Quick run command** | `venv/bin/python -m pytest tests/test_generation.py tests/test_session.py -x -q` |
| **Full suite command** | `venv/bin/python -m pytest -x -q` |
| **Estimated runtime** | ~10 seconds (offline tests); ~15s with live-DB tests |

---

## Sampling Rate

- **After every task commit:** Run `venv/bin/python -m pytest tests/test_generation.py tests/test_session.py -x -q`
- **After every plan wave:** Run `venv/bin/python -m pytest -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | GEN-01 | T-03-01 | System prompt grounding rules present | unit | `pytest tests/test_generation.py::test_system_prompt_contains_grounding_rules -x` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | GEN-01 | T-03-01 | Empty-context call returns refusal structure | unit | `pytest tests/test_generation.py::test_empty_sources_produces_refusal_structure -x` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | GEN-02 | — | Citation regex extracts `[S1]` correctly | unit | `pytest tests/test_generation.py::test_citation_regex_extracts_valid_refs -x` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | GEN-02 | — | Post-stream validator discards n > len(sources) | unit | `pytest tests/test_generation.py::test_citation_validator_discards_out_of_range -x` | ❌ W0 | ⬜ pending |
| 03-01-05 | 01 | 1 | GEN-07 | — | SSE generator yields session event first | unit (mock Anthropic) | `pytest tests/test_generation.py::test_stream_yields_session_event_first -x` | ❌ W0 | ⬜ pending |
| 03-01-06 | 01 | 1 | GEN-07 | — | SSE generator yields citations event last | unit (mock Anthropic) | `pytest tests/test_generation.py::test_stream_yields_citations_event_last -x` | ❌ W0 | ⬜ pending |
| 03-01-07 | 01 | 1 | CITE-02 | — | `event: citations` payload includes source_type field | unit | `pytest tests/test_generation.py::test_citations_payload_includes_source_type -x` | ❌ W0 | ⬜ pending |
| 03-01-08 | 01 | 1 | CITE-03 | — | Coverage indicator N = len(validated_citations) | unit | `pytest tests/test_generation.py::test_citation_count_equals_validated_sources -x` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 2 | CHAT-02 | — | Session store creates new session on unknown session_id | unit | `pytest tests/test_session.py::test_get_or_create_creates_new_session -x` | ❌ W0 | ⬜ pending |
| 03-03-02 | 03 | 2 | CHAT-02 | — | Session store returns existing session on known session_id | unit | `pytest tests/test_session.py::test_get_or_create_returns_existing -x` | ❌ W0 | ⬜ pending |
| 03-03-03 | 03 | 2 | CHAT-02 | — | Sliding window drops oldest pair when history exceeds MAX_MESSAGES | unit | `pytest tests/test_session.py::test_sliding_window_drops_oldest_pair -x` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 3 | CHAT-01, GEN-07 | — | `POST /chat` returns 200 and text/event-stream content-type | integration (mock Anthropic + mock retrieve) | `pytest tests/test_main.py::test_chat_endpoint_returns_event_stream -x` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 3 | CITE-01 | T-03-02 | `GET /sources/{chunk_id}` returns chunk text + source_type | integration (Postgres) | `pytest tests/test_main.py::test_get_source_returns_chunk_text -x -m integration` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 3 | GEN-01 | T-03-02 | No f-string SQL in `app/main.py` | static | `pytest tests/test_main.py::test_no_fstring_sql_in_main -x` | ❌ W0 | ⬜ pending |
| 03-04-01 | 04 | 4 | CHAT-01 | — | Frontend chat page renders empty state on load | manual (browser) | — | — | ⬜ pending |
| 03-04-02 | 04 | 4 | CHAT-03 | — | "New chat" button resets session and clears messages | manual (browser) | — | — | ⬜ pending |
| 03-04-03 | 04 | 4 | CITE-01, CITE-02 | — | Clicking citation pill opens drawer with source-type badge | manual (browser) | — | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_generation.py` — unit tests for prompt builder, citation regex, stream_response mock (GEN-01 through GEN-07, CITE-02, CITE-03)
- [ ] `tests/test_session.py` — unit tests for SessionStore sliding window (CHAT-02)
- [ ] `tests/test_main.py` — integration tests for `POST /chat` (mock Anthropic + mock retrieve) and `GET /sources/{chunk_id}` (live DB, skip if unreachable); static SQL guard (CHAT-01, CITE-01, GEN-01)

*Testing pattern: Use `starlette.testclient.TestClient` (no pytest-asyncio needed). Use `_FakeAnthropic` / `_FakeRetrieve` dependency injection following the `_FakeEmbedder` / `_FakeCursor` pattern from Phase 2.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Streaming tokens render in browser in real time with ▋ cursor | GEN-07, CHAT-01 | Requires live browser + FastAPI + Anthropic API | Run `uvicorn app.main:app`, open frontend, type gear + tone question, observe streaming |
| "New chat" clears messages and allows fresh session | CHAT-03 | React state reset requires live browser | Click "New Chat", verify message list clears, send new message, confirm no history bleed |
| Citation pill opens drawer with correct source text | CITE-01, CITE-02 | Requires live DB + running FastAPI | Click `[S1]` pill on a response, verify drawer shows correct chunk text and `[Forum]` badge |
| Corpus-silent query produces refusal | GEN-06 | Requires live Anthropic API + empty retrieval | Ask about a tone/gear not in the corpus, verify refusal message with reason |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
