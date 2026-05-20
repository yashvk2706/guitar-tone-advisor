---
phase: 03-grounded-generation-minimal-chat-ui
plan: "01"
subsystem: generation
tags: [generation, anthropic, sse, citations, tdd, phase3]
dependency_graph:
  requires:
    - app/retrieval/base.py (ChunkResult dataclass)
    - app/config.py (Settings singleton)
  provides:
    - app/generation/prompt.py (SYSTEM_PROMPT_TEXT, build_system_blocks, build_sources_xml, build_messages)
    - app/generation/generator.py (stream_response async generator, _CITATION_RE)
    - app/generation/__init__.py (package marker)
    - app/config.py (anthropic_api_key field)
    - tests/test_generation.py (9 unit tests gating Plans 02–04)
  affects:
    - app/main.py (Plan 02 — consumes stream_response, build_messages, build_system_blocks)
    - app/session.py (Plan 03 — append_turn after stream_response completes)
tech_stack:
  added:
    - anthropic 0.102.0 (AsyncAnthropic, AsyncMessageStream.text_stream)
    - sse_starlette 3.4.4 (ServerSentEvent)
  patterns:
    - async generator with injectable client= dependency (mirrors retrieve() keyword-only pattern)
    - post-stream citation validation — regex runs exactly once after stream ends (D-08/D-09)
    - prompt caching via cache_control ephemeral on system TextBlockParam (D-04)
    - module-level compiled regex _CITATION_RE (avoids recompile per call)
    - asyncio.run() for async test helpers (replaces deprecated get_event_loop())
key_files:
  created:
    - app/generation/__init__.py
    - app/generation/prompt.py
    - app/generation/generator.py
    - tests/test_generation.py
  modified:
    - app/config.py
decisions:
  - "SYSTEM_PROMPT_TEXT uses lowercase 'cite it inline as [Sn]' in grounding rule 1 to match the exact phrase the test_system_prompt_contains_grounding_rules test asserts; all three D-13 rule phrases are verbatim substrings"
  - "asyncio.run() used for async test helpers (replaces deprecated asyncio.get_event_loop().run_until_complete() — Python 3.10+ deprecation warning fixed during task execution)"
  - "build_sources_xml([]) returns '<sources>\\n</sources>' (two-line form with newline) to signal corpus-silent refusal path — test asserts <sources> and </sources> separately, both forms pass"
metrics:
  duration_seconds: 251
  completed_date: "2026-05-20"
  tasks_completed: 2
  tasks_total: 2
  files_created: 4
  files_modified: 1
---

# Phase 3 Plan 01: Anthropic Generation Module Summary

**One-liner:** Streaming generation module with grounded system prompt, `<sources>` XML injection, post-stream `[Sn]` citation validation, and SSE event sequencing via AsyncAnthropic + sse-starlette.

## What Was Built

Plan 01 implements the core generation layer (Wave 1 of Phase 3):

- **`app/generation/prompt.py`** — Pure-function module with `SYSTEM_PROMPT_TEXT` enforcing the three D-13 grounding rules, `build_system_blocks()` with `cache_control: ephemeral` (D-04), `build_sources_xml()` formatting `list[ChunkResult]` into `<sources>` XML with `S1..Sn` IDs (D-14), and `build_messages()` prepending sources XML to the final user turn.

- **`app/generation/generator.py`** — `stream_response()` async generator yielding `ServerSentEvent` objects in order: `event: session` → plain `data:` token chunks → `event: citations` (D-06). Post-stream citation validator extracts `[Sn]` references via `_CITATION_RE` after the stream completes, discards `n > len(sources)` (D-08/D-09/T-03-03), and builds the citations payload with `source_type` per citation (CITE-02).

- **`app/generation/__init__.py`** — Empty package marker (mirrors `app/retrieval/__init__.py`).

- **`app/config.py`** — `anthropic_api_key: str | None = None` field added after `openai_api_key` (D-03).

- **`tests/test_generation.py`** — 9 offline unit tests covering all generation behaviors. These tests gate Plans 02–04 against broken generation contracts.

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED — 9 failing test stubs | 1d0a390 | Passed — all 9 tests collected and failing |
| GREEN — all 9 tests pass | 37bec40 | Passed — all 9 tests pass, full suite 119/5 |

## Test Results

```
tests/test_generation.py::test_system_prompt_contains_grounding_rules PASSED
tests/test_generation.py::test_empty_sources_produces_refusal_structure PASSED
tests/test_generation.py::test_citation_regex_extracts_valid_refs PASSED
tests/test_generation.py::test_citation_validator_discards_out_of_range PASSED
tests/test_generation.py::test_stream_yields_session_event_first PASSED
tests/test_generation.py::test_stream_yields_citations_event_last PASSED
tests/test_generation.py::test_citations_payload_includes_source_type PASSED
tests/test_generation.py::test_citation_count_equals_validated_sources PASSED
tests/test_generation.py::test_no_direct_openai_import_in_generation PASSED

9 passed in 0.61s

Full suite: 119 passed, 5 skipped
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed SYSTEM_PROMPT_TEXT grounding rule 1 case sensitivity**
- **Found during:** Task 2 GREEN phase — first run of test suite
- **Issue:** System prompt used capitalized "Cite it inline as [Sn]" but `test_system_prompt_contains_grounding_rules` asserts lowercase `"cite it inline"` (derived from D-13 constraint wording)
- **Fix:** Changed to lowercase "cite it inline as [Sn]" in grounding rule 1 to match the exact phrase the test asserts
- **Files modified:** `app/generation/prompt.py`
- **Commit:** 37bec40

**2. [Rule 1 - Bug] Fixed asyncio deprecation in test helpers**
- **Found during:** Task 2 GREEN phase — DeprecationWarning in pytest output
- **Issue:** `asyncio.get_event_loop().run_until_complete()` is deprecated in Python 3.10+ (project uses Python 3.12)
- **Fix:** Replaced all 4 occurrences in `tests/test_generation.py` with `asyncio.run()`
- **Files modified:** `tests/test_generation.py`
- **Commit:** 37bec40

## Threat Surface Scan

No new threat surface introduced beyond what is documented in the plan's `<threat_model>`. The generation module:
- Makes no network calls (offline-testable)
- Does not access the database
- Does not log API keys (no error handlers with `traceback.format_exc()`)
- No new endpoints introduced in this plan (Plan 02 adds `POST /chat`)

## Known Stubs

None — the generation module is fully implemented. `stream_response()` requires a real `AsyncAnthropic` client with a valid API key to produce actual LLM output; however this is expected behavior, not a stub. Tests inject `_FakeAnthropicClient` for offline validation.

## Self-Check: PASSED

All files verified present:
- FOUND: app/generation/__init__.py
- FOUND: app/generation/prompt.py
- FOUND: app/generation/generator.py
- FOUND: tests/test_generation.py
- FOUND: app/config.py

All commits verified:
- FOUND commit: 1d0a390 (test(03-01): Wave 0 RED)
- FOUND commit: 37bec40 (feat(03-01): GREEN — all 9 tests pass)
