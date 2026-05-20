"""Generation module tests — Phase 3 Plan 01.

9 named tests total: 9 offline unit (no live-DB required).

Covers:
  - prompt module grounding rules (GEN-01)
  - citation regex pattern (GEN-02)
  - post-stream citation validator — discards n > len(sources) (GEN-02, CITE-03)
  - SSE event sequence: session → tokens → citations (GEN-07)
  - source_type field in event: citations payload (CITE-02)
  - no-openai-import static guard (CLAUDE.md constraint)

All 9 tests fail (RED) at creation time because app/generation/ does not yet exist.
Imports are placed inside each test function body to ensure collection succeeds even
when the module is absent.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from app.retrieval.base import ChunkResult


# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------


def _make_chunk_result(
    chunk_id: str = "chunk-id-1",
    document_id: str = "doc-id-1",
    source_type: str = "forum",
    source_name: str = "bb_king_tone.txt",
    chunk_index: int = 0,
    text: str = "Some representative chunk text about tone.",
    distance: float = 0.15,
) -> ChunkResult:
    """Return a ChunkResult with sensible defaults for test use."""
    return ChunkResult(
        chunk_id=chunk_id,
        document_id=document_id,
        source_type=source_type,
        source_name=source_name,
        chunk_index=chunk_index,
        text=text,
        distance=distance,
    )


# ---------------------------------------------------------------------------
# Fake Anthropic streaming objects
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

    Prevents session state bleed even though session.py is not Plan 1's target.
    The import is safe because the module will exist when Plan 3 runs.
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
# Test 1: system prompt grounding rules
# ---------------------------------------------------------------------------


def test_system_prompt_contains_grounding_rules():
    """SYSTEM_PROMPT_TEXT must contain all three grounding rule keywords from D-13."""
    from app.generation.prompt import SYSTEM_PROMPT_TEXT  # type: ignore[import-not-found]

    assert "cite it inline" in SYSTEM_PROMPT_TEXT, (
        "Rule 1 phrase 'cite it inline' not found in SYSTEM_PROMPT_TEXT"
    )
    assert "refuse" in SYSTEM_PROMPT_TEXT, (
        "Rule 2 keyword 'refuse' not found in SYSTEM_PROMPT_TEXT"
    )
    assert "Never cite" in SYSTEM_PROMPT_TEXT, (
        "Rule 3 phrase 'Never cite' not found in SYSTEM_PROMPT_TEXT"
    )


# ---------------------------------------------------------------------------
# Test 2: empty sources produces refusal structure
# ---------------------------------------------------------------------------


def test_empty_sources_produces_refusal_structure():
    """build_messages() with empty sources list must produce a message whose
    content contains a <sources> tag pair — signals the refusal path to the model."""
    from app.generation.prompt import build_messages  # type: ignore[import-not-found]

    messages = build_messages(turns=[], user_message="test", sources=[])
    assert len(messages) >= 1, "build_messages must return at least one message"
    last_user_msg = messages[-1]
    assert last_user_msg["role"] == "user"
    content = last_user_msg["content"]
    # Accept either form: "<sources>\n</sources>" or "<sources></sources>"
    assert "<sources>" in content, "content must contain opening <sources> tag"
    assert "</sources>" in content, "content must contain closing </sources> tag"


# ---------------------------------------------------------------------------
# Test 3: citation regex extracts valid refs
# ---------------------------------------------------------------------------


def test_citation_regex_extracts_valid_refs():
    """The citation regex r'\\[S(\\d+)\\]' must extract numeric groups from [Sn] refs."""
    pattern = re.compile(r"\[S(\d+)\]")
    result = pattern.findall("[S1] some text [S2] more [S3]")
    assert result == ["1", "2", "3"], (
        f"expected ['1', '2', '3'], got {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: post-stream validator discards out-of-range citations
# ---------------------------------------------------------------------------


def test_citation_validator_discards_out_of_range():
    """Given response_text='[S1] [S3]' and sources of length 2,
    the validated citation set must contain only {1} (S3 discarded because 3 > 2)."""
    # Import the compiled regex from the generator module (RED: will fail until GREEN)
    from app.generation.generator import _CITATION_RE  # type: ignore[import-not-found]

    response_text = "[S1] [S3]"
    sources = [_make_chunk_result(chunk_id=f"id-{i}") for i in range(2)]

    raw_ns = {int(n) for n in _CITATION_RE.findall(response_text)}
    valid_ns = {n for n in raw_ns if 1 <= n <= len(sources)}

    assert valid_ns == {1}, (
        f"Expected only {{1}} after validation but got {valid_ns!r}"
    )


# ---------------------------------------------------------------------------
# Test 5: stream yields session event first
# ---------------------------------------------------------------------------


def test_stream_yields_session_event_first():
    """stream_response() must yield a ServerSentEvent with event='session' as the
    very first event."""
    from app.generation.generator import stream_response  # type: ignore[import-not-found]

    fake_client = _FakeAnthropicClient(tokens=["hello"])
    sources: list[ChunkResult] = []

    async def _collect():
        events = []
        async for sse in stream_response(
            client=fake_client,
            system_blocks=[{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": "test"}],
            sources=sources,
            session_id="test-session-id",
        ):
            events.append(sse)
        return events

    events = asyncio.run(_collect())
    assert len(events) >= 1, "stream_response must yield at least one event"
    assert events[0].event == "session", (
        f"First event must have event='session', got {events[0].event!r}"
    )


# ---------------------------------------------------------------------------
# Test 6: stream yields citations event last
# ---------------------------------------------------------------------------


def test_stream_yields_citations_event_last():
    """stream_response() must yield a ServerSentEvent with event='citations' as the
    very last event."""
    from app.generation.generator import stream_response  # type: ignore[import-not-found]

    fake_client = _FakeAnthropicClient(tokens=["hello"])
    sources: list[ChunkResult] = []

    async def _collect():
        events = []
        async for sse in stream_response(
            client=fake_client,
            system_blocks=[{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": "test"}],
            sources=sources,
            session_id="test-session-id",
        ):
            events.append(sse)
        return events

    events = asyncio.run(_collect())
    assert len(events) >= 1, "stream_response must yield at least one event"
    assert events[-1].event == "citations", (
        f"Last event must have event='citations', got {events[-1].event!r}"
    )


# ---------------------------------------------------------------------------
# Test 7: citations payload includes source_type
# ---------------------------------------------------------------------------


def test_citations_payload_includes_source_type():
    """The event: citations payload must include source_type for each valid citation."""
    from app.generation.generator import stream_response  # type: ignore[import-not-found]

    # Use a token that references S1 so it appears in the citations payload
    fake_client = _FakeAnthropicClient(tokens=["[S1] warm tone"])
    sources = [_make_chunk_result(source_type="forum")]

    async def _collect():
        events = []
        async for sse in stream_response(
            client=fake_client,
            system_blocks=[{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": "test"}],
            sources=sources,
            session_id="test-session-id",
        ):
            events.append(sse)
        return events

    events = asyncio.run(_collect())
    citations_event = events[-1]
    assert citations_event.event == "citations", "Last event must be citations"
    payload = json.loads(citations_event.data)
    assert "sources" in payload, "citations payload must contain 'sources' key"
    assert len(payload["sources"]) >= 1, "citations payload sources list must not be empty"
    assert payload["sources"][0]["source_type"] == "forum", (
        f"Expected source_type 'forum', got {payload['sources'][0].get('source_type')!r}"
    )


# ---------------------------------------------------------------------------
# Test 8: citation count equals validated sources
# ---------------------------------------------------------------------------


def test_citation_count_equals_validated_sources():
    """With response_text '[S1] [S2]' and sources list len=3,
    the citations payload must contain exactly 2 sources."""
    from app.generation.generator import stream_response  # type: ignore[import-not-found]

    # Tokens that reference [S1] and [S2]; S3 exists but is not referenced
    fake_client = _FakeAnthropicClient(tokens=["[S1]", " text ", "[S2]"])
    sources = [
        _make_chunk_result(chunk_id=f"id-{i}", source_name=f"src{i}.txt")
        for i in range(3)
    ]

    async def _collect():
        events = []
        async for sse in stream_response(
            client=fake_client,
            system_blocks=[{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": "test"}],
            sources=sources,
            session_id="test-session-id",
        ):
            events.append(sse)
        return events

    events = asyncio.run(_collect())
    citations_event = events[-1]
    payload = json.loads(citations_event.data)
    assert len(payload["sources"]) == 2, (
        f"Expected exactly 2 validated sources, got {len(payload['sources'])}"
    )


# ---------------------------------------------------------------------------
# Test 9: no direct openai import in app/generation/
# ---------------------------------------------------------------------------


def test_no_direct_openai_import_in_generation():
    """No file in app/generation/ may directly import openai (CLAUDE.md constraint)."""
    generation_dir = Path(__file__).resolve().parent.parent / "app" / "generation"
    assert generation_dir.exists(), (
        f"app/generation/ directory not found at {generation_dir}"
    )
    pattern = re.compile(r"^(from openai\b|import openai\b)", re.MULTILINE)
    violators = [
        str(f)
        for f in generation_dir.rglob("*.py")
        if pattern.search(f.read_text(encoding="utf-8"))
    ]
    assert violators == [], (
        f"Direct openai import found in app/generation/: {violators}"
    )
