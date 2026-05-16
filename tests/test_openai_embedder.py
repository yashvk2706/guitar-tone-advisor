"""Direct tests for ``OpenAIEmbedder``: shape, batching, retry, no-network.

Mocking strategy:
    We patch ``app.embeddings.openai_embedder.OpenAI`` with a small ``FakeClient``
    so no real network call ever happens. Each test that needs to count calls
    inspects ``FakeClient.calls``.

Retry tests neutralize ``tenacity``'s exponential backoff so the test suite
stays fast: ``embedder.embed_documents.retry.wait = wait_fixed(0)`` mutates
only that bound method's retry policy for the test's lifetime. This is the
pattern the plan asked us to document — it's far cleaner than patching
``wait_exponential`` at the module level.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from tenacity import wait_fixed

# Ensure project root is importable.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeEmbeddingItem:
    """Mirrors the ``data[i]`` shape that openai-python returns: an object with
    an ``.embedding`` attribute (a list[float]).
    """

    __slots__ = ("embedding",)

    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding


class _FakeEmbeddingsResponse:
    """Mirrors ``client.embeddings.create(...)``'s return shape: ``.data`` is
    a list of items, each with ``.embedding``.
    """

    __slots__ = ("data",)

    def __init__(self, vectors: list[list[float]]) -> None:
        self.data = [_FakeEmbeddingItem(v) for v in vectors]


class _FakeEmbeddingsNamespace:
    """Namespace exposing the ``.create`` method, recording call args and
    optionally raising on the first ``raises_first_n`` invocations.
    """

    def __init__(
        self,
        dim: int = 1536,
        raises_first_n: int = 0,
    ) -> None:
        self.dim = dim
        self._raises_first_n = raises_first_n
        self.calls: list[dict[str, Any]] = []

    def create(self, *, model: str, input: list[str], **_kwargs):
        self.calls.append({"model": model, "input": list(input)})
        if len(self.calls) <= self._raises_first_n:
            raise RuntimeError("simulated transient failure")
        # Return one deterministic vector per input.
        vectors = [[0.001 * (idx + 1)] * self.dim for idx in range(len(input))]
        return _FakeEmbeddingsResponse(vectors)


class _FakeClient:
    """Stand-in for the ``OpenAI`` client. Only the ``.embeddings`` namespace
    is needed for these tests.
    """

    def __init__(self, dim: int = 1536, raises_first_n: int = 0, **_ignored: Any) -> None:
        self.embeddings = _FakeEmbeddingsNamespace(dim=dim, raises_first_n=raises_first_n)


def _install_fake_client(monkeypatch, **kwargs) -> _FakeClient:
    """Patch ``OpenAI`` in the embedder module so its constructor returns our fake.

    Returns the constructed ``_FakeClient`` so the test can inspect call records.
    """
    fake_holder: dict[str, _FakeClient] = {}

    def _factory(*_args: Any, **_kwargs: Any) -> _FakeClient:
        client = _FakeClient(**kwargs)
        fake_holder["client"] = client
        return client

    monkeypatch.setattr("app.embeddings.openai_embedder.OpenAI", _factory)
    return fake_holder  # populated lazily on first instantiation


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_attrs(monkeypatch):
    """Constructor pins provider / model / dim from the locked _DIMS table."""
    _install_fake_client(monkeypatch)
    from app.embeddings.openai_embedder import OpenAIEmbedder

    e = OpenAIEmbedder()
    assert e.provider == "openai"
    assert e.model == "text-embedding-3-small"
    assert e.dim == 1536


def test_embed_documents_returns_embedding_result(monkeypatch):
    """Happy path: 3 inputs → EmbeddingResult with 3 vectors of length 1536."""
    holder = _install_fake_client(monkeypatch)
    from app.embeddings.base import EmbeddingResult
    from app.embeddings.openai_embedder import OpenAIEmbedder

    e = OpenAIEmbedder()
    result = e.embed_documents(["a", "b", "c"])

    assert isinstance(result, EmbeddingResult)
    assert result.model == "text-embedding-3-small"
    assert result.dim == 1536
    assert result.provider == "openai"
    assert len(result.vectors) == 3
    assert all(len(v) == 1536 for v in result.vectors)
    assert holder["client"].embeddings.calls[0]["model"] == "text-embedding-3-small"


def test_embed_documents_batches_at_64(monkeypatch):
    """130 inputs → exactly 3 create() calls (64 + 64 + 2)."""
    holder = _install_fake_client(monkeypatch)
    from app.embeddings.openai_embedder import OpenAIEmbedder

    e = OpenAIEmbedder()
    texts = [f"text-{i}" for i in range(130)]
    result = e.embed_documents(texts)

    calls = holder["client"].embeddings.calls
    assert len(calls) == 3, f"expected 3 batches, got {len(calls)}"
    assert len(calls[0]["input"]) == 64
    assert len(calls[1]["input"]) == 64
    assert len(calls[2]["input"]) == 2
    assert len(result.vectors) == 130
    # Order preserved: first input maps to first vector.
    assert calls[0]["input"][0] == "text-0"
    assert calls[2]["input"][-1] == "text-129"


def test_embed_query_returns_single_vector(monkeypatch):
    """embed_query returns a raw list[float], not an EmbeddingResult."""
    _install_fake_client(monkeypatch)
    from app.embeddings.openai_embedder import OpenAIEmbedder

    e = OpenAIEmbedder()
    vec = e.embed_query("how do I sound like BB King")

    assert isinstance(vec, list)
    assert len(vec) == 1536
    assert all(isinstance(x, float) for x in vec)


def test_embed_documents_and_embed_query_are_separate_methods(monkeypatch):
    """CLAUDE.md hard constraint: the two methods MUST be distinct callables."""
    _install_fake_client(monkeypatch)
    from app.embeddings.openai_embedder import OpenAIEmbedder

    e = OpenAIEmbedder()
    assert e.embed_documents.__name__ == "embed_documents"
    assert e.embed_query.__name__ == "embed_query"
    # And the underlying functions are not the same callable.
    assert OpenAIEmbedder.embed_documents is not OpenAIEmbedder.embed_query


def test_retries_on_transient_failure(monkeypatch):
    """Tenacity retries up to 5 attempts; first 2 fail then 3rd succeeds.

    We zero out the exponential backoff so the test runs in <50ms instead of
    waiting for the real wait_exponential(min=1, max=30) ladder.
    """
    holder = _install_fake_client(monkeypatch, raises_first_n=2)
    from app.embeddings.openai_embedder import OpenAIEmbedder

    e = OpenAIEmbedder()
    # Neutralize backoff for this test only — see module docstring.
    e.embed_documents.retry.wait = wait_fixed(0)

    result = e.embed_documents(["x"])
    assert len(result.vectors) == 1
    assert len(holder["client"].embeddings.calls) == 3


def test_dim_lookup_for_large(monkeypatch):
    """text-embedding-3-large is 3072-d."""
    _install_fake_client(monkeypatch, dim=3072)
    from app.embeddings.openai_embedder import OpenAIEmbedder

    e = OpenAIEmbedder(model="text-embedding-3-large")
    assert e.dim == 3072


def test_unknown_model_raises(monkeypatch):
    """Unknown OpenAI model name raises KeyError — fail loud, don't silently embed
    at the wrong dimensionality.
    """
    _install_fake_client(monkeypatch)
    from app.embeddings.openai_embedder import OpenAIEmbedder

    with pytest.raises(KeyError):
        OpenAIEmbedder(model="text-embedding-9000")
