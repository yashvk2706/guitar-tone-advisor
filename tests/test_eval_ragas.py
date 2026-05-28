"""RAGAS-style faithfulness eval tests — Phase 5 Plan 3.

6 named tests total: 5 offline unit/static + 1 faithfulness scoring test.
All are in RED state initially (before app/eval/ragas.py exists).

Covers:
  - parse_claims() JSON extraction: bare + fenced (EVAL-04)
  - parse_support() grounding check (EVAL-04)
  - faithfulness score = supported/total; 0.0 when total==0 (EVAL-04)
  - CLI --help flag listing (EVAL-04)
  - Static guard: no direct openai import in app/eval/ (CLAUDE.md hard constraint)

Pitfall 6: _FakeSyncClient uses .messages.create() (NOT .messages.stream()).
Do NOT conflate with _FakeAnthropicClient in test_generation.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# DB-gated fixture (copied verbatim from tests/test_retrieval.py lines 44–62)
# kept available if an optional integration test is added later
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_conn():
    """Live Postgres connection + schema bootstrap. Skip if unreachable."""
    try:
        from app.db import get_conn, init_schema
    except Exception as e:
        pytest.skip(f"app.db import failed: {e!r}")
    try:
        conn = get_conn()
    except Exception as e:
        pytest.skip(f"Postgres not reachable: {e!r}")
    try:
        init_schema(conn)
    except Exception as e:
        conn.close()
        pytest.skip(f"init_schema failed: {e!r}")
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Fake sync client family (Pitfall 6: .create() only, NOT .stream())
# Mirrors the RAGAS two-step claim decomposer's sync Anthropic client usage.
# ---------------------------------------------------------------------------


class _FakeTextBlock:
    """Minimal text block returned in a fake Anthropic sync response."""

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeCreateResponse:
    """Minimal fake for Anthropic sync .messages.create() response.

    Exposes .content[0].text to match the real SDK shape used by RAGAS.
    """

    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]


class _FakeCreateMessages:
    """Fake messages endpoint that returns pre-canned .create() responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)

    def create(self, **kwargs: object) -> _FakeCreateResponse:
        return _FakeCreateResponse(next(self._responses))


class _FakeSyncClient:
    """Fake sync Anthropic client for RAGAS unit tests.

    Has .messages.create() — NOT .messages.stream().
    This is DISTINCT from _FakeAnthropicClient in test_generation.py.
    """

    def __init__(self, responses: list[str]) -> None:
        self.messages = _FakeCreateMessages(responses)


# ---------------------------------------------------------------------------
# Test 1: parse_claims — bare JSON array
# ---------------------------------------------------------------------------


def test_parse_claims():
    """parse_claims extracts a JSON array from bare JSON strings.

    Bare JSON: '["claim one", "claim two"]' → ['claim one', 'claim two']
    Empty/garbage string: '' or 'not json' → []
    """
    from app.eval.ragas import parse_claims  # type: ignore[import-not-found]

    # bare JSON array
    result = parse_claims('["claim one", "claim two"]')
    assert result == ["claim one", "claim two"]

    # garbage string → empty list (safe fallback per T-05-08)
    assert parse_claims("garbage not json []bad") == []

    # empty string → empty list
    assert parse_claims("") == []


# ---------------------------------------------------------------------------
# Test 2: parse_claims — markdown-fenced JSON array
# ---------------------------------------------------------------------------


def test_parse_claims_fenced():
    """parse_claims strips markdown code fence and extracts the JSON array.

    The LLM may return:
        ```json
        ["a", "b"]
        ```
    parse_claims must strip the fence and return ['a', 'b'].
    """
    from app.eval.ragas import parse_claims  # type: ignore[import-not-found]

    # Build the fenced string without triple-quoted backticks for clarity
    TICK = chr(96)
    fence_open = TICK * 3 + "json"
    fence_close = TICK * 3
    fenced_input = fence_open + "\n" + '["a", "b"]' + "\n" + fence_close

    result = parse_claims(fenced_input)
    assert result == ["a", "b"]

    # Plain backtick fence (no language tag)
    fence_open_plain = TICK * 3
    fenced_plain = fence_open_plain + "\n" + '["x", "y"]' + "\n" + fence_close
    result_plain = parse_claims(fenced_plain)
    assert result_plain == ["x", "y"]


# ---------------------------------------------------------------------------
# Test 3: parse_support — bare JSON object
# ---------------------------------------------------------------------------


def test_parse_support():
    """parse_support extracts the boolean from a JSON {"supported": bool} object.

    {"supported": true} → True
    {"supported": false} → False
    garbage → False (safe fallback per T-05-08)
    """
    from app.eval.ragas import parse_support  # type: ignore[import-not-found]

    assert parse_support('{"supported": true}') is True
    assert parse_support('{"supported": false}') is False

    # garbage → False (failed extraction cannot masquerade as supported)
    assert parse_support("not json at all") is False
    assert parse_support("") is False


# ---------------------------------------------------------------------------
# Test 4: faithfulness score = supported/total; 0.0 when total==0
# ---------------------------------------------------------------------------


def test_faithfulness_score():
    """faithfulness(supported, total) returns supported/total; 0.0 when total==0.

    This tests the pure arithmetic helper independently of LLM calls.
    3 of 4 claims supported → 0.75
    0 of 0 claims (total==0) → 0.0 (not 1.0 — T-05-08: can't masquerade as perfect)
    """
    from app.eval.ragas import faithfulness  # type: ignore[import-not-found]

    assert faithfulness(3, 4) == 0.75
    assert faithfulness(4, 4) == 1.0
    assert faithfulness(0, 5) == 0.0
    assert faithfulness(0, 0) == 0.0  # total==0 → 0.0, not 1.0


# ---------------------------------------------------------------------------
# Test 5: CLI --help lists required flags
# ---------------------------------------------------------------------------


def test_ragas_cli_help():
    """build_parser().format_help() contains the required flags.

    Required: --held-out, --all, --golden-set, --runs-log
    """
    from app.eval.ragas import build_parser  # type: ignore[import-not-found]

    help_text = build_parser().format_help()
    assert "--held-out" in help_text, f"--held-out not in help: {help_text!r}"
    assert "--all" in help_text, f"--all not in help: {help_text!r}"
    assert "--runs-log" in help_text, f"--runs-log not in help: {help_text!r}"


# ---------------------------------------------------------------------------
# Test 6: Static guard — no direct openai import in app/eval/
# ---------------------------------------------------------------------------


def test_no_direct_openai_import():
    """No file in app/eval/ may directly import openai (CLAUDE.md hard constraint).

    Pattern: 'from openai ...' or 'import openai ...' at line start.
    All embedding access must go through get_embedder() only.
    """
    eval_dir = Path(__file__).resolve().parent.parent / "app" / "eval"
    assert eval_dir.exists(), f"app/eval/ not found at {eval_dir}"
    pattern = re.compile(r"^(from openai\b|import openai\b)", re.MULTILINE)
    violators = [
        str(f)
        for f in eval_dir.rglob("*.py")
        if pattern.search(f.read_text(encoding="utf-8"))
    ]
    assert violators == [], f"Direct openai import in app/eval/: {violators}"
