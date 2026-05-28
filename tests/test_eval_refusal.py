"""Refusal contract smoke tests — Phase 5 Plan 02.

4 tests total: 3 offline unit + 1 live integration (gated on ANTHROPIC_API_KEY).

These tests enforce GEN-06's refusal contract: when the corpus is empty or
adversarially mismatched, the generation layer must produce a refusal phrase
and must NOT fabricate knob/setting values.

All tests call stream_response() DIRECTLY — never via the HTTP endpoint.
The HTTP path (test_main.py) uses raise_server_exceptions=False which silently
swallows TypeError from parameter name mismatches — Pitfall 5.
"""

from __future__ import annotations

import asyncio
import json
import os
import re

import pytest

from app.retrieval.base import ChunkResult


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

REFUSAL_PHRASES = ("I don't have material", "the closest I have")

# Knob/setting pattern: e.g. "Gain=7", "Bass: 6", "Treble=8.5"
_KNOB_RE = re.compile(r"[A-Za-z][A-Za-z\s]{0,15}[:=]\s*\d+(?:\.\d+)?")

# A fabricated response that contains knob settings but no refusal phrase.
# Used in test_empty_context_refusal_assertion to verify the negative-assertion
# machinery correctly identifies fabrication.
_FABRICATED_EVH_RESPONSE = (
    "Set your amp to Gain=7, Bass=6, Mid=4, Treble=8. "
    "Use the 5150 lead channel for maximum brown sound crunch."
)


# ---------------------------------------------------------------------------
# Fake Anthropic streaming objects (verbatim copy from test_generation.py)
# ---------------------------------------------------------------------------


class _FakeAnthropicStream:
    """Async context manager that yields pre-determined tokens via .text_stream."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    async def __aenter__(self) -> "_FakeAnthropicStream":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    @property
    def text_stream(self):
        """Async generator yielding token strings from the constructor list."""

        async def _gen():
            for t in self._tokens:
                yield t

        return _gen()


class _FakeAnthropicClient:
    """Injectable replacement for AsyncAnthropic in stream_response() tests."""

    def __init__(self, tokens: list[str] | None = None) -> None:
        self._tokens = tokens if tokens is not None else ["hello"]
        self.messages = _FakeMessages(self._tokens)


class _FakeMessages:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    def stream(self, **kwargs: object) -> _FakeAnthropicStream:
        return _FakeAnthropicStream(self._tokens)


# ---------------------------------------------------------------------------
# autouse fixture — clears session state between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_sessions():
    """Clear app.session._sessions before and after each test.

    Prevents session state bleed even though session.py is not this plan's
    primary target.
    """
    try:
        import app.session as s
        s._sessions.clear()
    except (ImportError, AttributeError):
        pass
    yield
    try:
        import app.session as s
        s._sessions.clear()
    except (ImportError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# Live integration fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def anthropic_key():
    """Provide the ANTHROPIC_API_KEY or skip the test if it is not set."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set — skipping live refusal integration test")
    return key


# ---------------------------------------------------------------------------
# Async helper — drains stream_response() into a plain text string
# ---------------------------------------------------------------------------


async def _collect(
    client,
    sources_with_ids: list[tuple[ChunkResult, int]],
    user_message: str = "Get EVH gain tone",
) -> str:
    """Drain stream_response() and return the concatenated token text.

    Filters on sse.event is None (plain token data events) and reads
    payload["text"], matching generator.py line 97:
        yield ServerSentEvent(data=json.dumps({"text": text}))
    """
    from app.generation.generator import stream_response
    from app.generation.prompt import build_system_blocks, build_messages

    parts: list[str] = []
    async for sse in stream_response(
        client=client,
        system_blocks=build_system_blocks(),
        messages=build_messages([], user_message, sources_with_ids),
        sources_with_ids=sources_with_ids,
        session_id="test-refusal",
    ):
        if sse.event is None:
            payload = json.loads(sse.data)
            if "text" in payload:
                parts.append(payload["text"])
    return "".join(parts)


# ---------------------------------------------------------------------------
# Test 1: negative-assertion machinery correctly identifies fabrication
# ---------------------------------------------------------------------------


def test_empty_context_refusal_assertion():
    """Confirm that the assertion machinery detects a fabricated (non-refusal) response.

    _FABRICATED_EVH_RESPONSE does NOT contain any refusal phrase and DOES contain
    knob-setting matches — the negative path in the assertion logic must confirm:
      - assert not any(phrase in text for phrase in REFUSAL_PHRASES)  → passes
      - assert _KNOB_RE.findall(text)                                 → passes (matches found)

    This test proves the detection machinery works before testing the real model
    path in tests 2 and 3.
    """
    text = _FABRICATED_EVH_RESPONSE
    assert not any(p in text for p in REFUSAL_PHRASES), (
        f"Fabricated response unexpectedly contains a refusal phrase: {text!r}"
    )
    assert _KNOB_RE.findall(text), (
        f"Fabricated response did not trip _KNOB_RE — machinery broken: {text!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: empty corpus → model should produce a refusal phrase
# ---------------------------------------------------------------------------


def test_empty_context_produces_refusal():
    """When sources_with_ids=[], the faked model response must contain a refusal phrase.

    The fake client streams a pre-canned refusal token — this verifies that
    _collect() correctly extracts the token text AND that the refusal-phrase
    assertion fires as expected.
    """
    fake = _FakeAnthropicClient(
        tokens=["I don't have material on EVH — the closest I have is the Marshall JCM800"]
    )
    text = asyncio.run(_collect(fake, sources_with_ids=[]))
    assert any(p in text for p in REFUSAL_PHRASES), (
        f"Expected a refusal phrase in empty-context response, got: {text!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: adversarial mismatch → refusal AND no knob-setting patterns
# ---------------------------------------------------------------------------


def test_adversarial_mismatch_no_knobs():
    """When sources_with_ids contains only a lo-fi chunk (wrong context for EVH query),
    the faked response must contain a refusal phrase AND contain zero knob-setting
    pattern matches.

    This verifies the combined contract:
    1. The model (or fake) refuses when context is mismatched.
    2. The refusal text itself does not accidentally contain fabricated settings.
    """
    lo_fi_chunk = ChunkResult(
        chunk_id="11547f9a-2b6b-4074-a301-80113ee72bea",
        document_id="doc-lofi-1",
        source_type="forum",
        source_name="lo_fi_tone.txt",
        chunk_index=0,
        text="For lo-fi bedroom guitar tone, use a cheap amp mic'd badly with tape hiss.",
        distance=0.6,
    )
    sources_with_ids = [(lo_fi_chunk, 1)]

    fake = _FakeAnthropicClient(
        tokens=[
            "I don't have material on the EVH brown sound — "
            "the closest I have is lo-fi bedroom tone, want that instead?"
        ]
    )
    text = asyncio.run(_collect(fake, sources_with_ids=sources_with_ids))

    assert any(p in text for p in REFUSAL_PHRASES), (
        f"Expected a refusal phrase in adversarial-mismatch response, got: {text!r}"
    )
    assert _KNOB_RE.findall(text) == [], (
        f"Refusal response must not contain knob-setting patterns, found: "
        f"{_KNOB_RE.findall(text)!r} in {text!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: live integration — real model refuses with empty context
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_empty_context_produces_refusal(anthropic_key: str):
    """Live integration test: the real Claude model must refuse when given empty context.

    Gated on ANTHROPIC_API_KEY — skipped automatically when the key is absent.
    Exercises the real stream_response() → Anthropic API path end-to-end.
    """
    from anthropic import AsyncAnthropic

    real_client = AsyncAnthropic(api_key=anthropic_key)
    text = asyncio.run(_collect(real_client, sources_with_ids=[]))

    assert any(p in text for p in REFUSAL_PHRASES), (
        f"Real model did not refuse with empty context. Response was: {text!r}"
    )
