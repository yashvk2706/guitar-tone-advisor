"""Embedder Protocol conformance + factory dispatch tests.

These tests assert the architectural contract from CLAUDE.md:
    * ``embed_documents()`` and ``embed_query()`` exist as separate methods
      (never conflated).
    * Only ``app/embeddings/openai_embedder.py`` may import the ``openai``
      package — every other module routes through the ``Embedder`` protocol.
    * The factory dispatches on ``EMBEDDING_MODEL`` and raises
      ``NotImplementedError`` for backends that Phase 1 has not implemented yet
      (Voyage / local), and ``ValueError`` for genuinely unknown names.

Each factory-dispatch test uses ``monkeypatch.setenv`` + ``get_settings.cache_clear()``
because ``app.config.get_settings`` is decorated with ``@lru_cache`` (a stale cache
would otherwise return the previous test's Settings instance).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import get_type_hints

import pytest

# Ensure the project root is importable when pytest is run from outside the venv shell.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Clear the lru_cache on ``get_settings`` before and after every test.

    Tests in this module mutate the ``EMBEDDING_MODEL`` env var via monkeypatch;
    without this fixture the cached Settings would survive across tests and the
    factory would dispatch on a stale model name.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_embedding_result_is_frozen_dataclass():
    """``EmbeddingResult`` must be immutable so callers can't mutate a returned batch."""
    from app.embeddings.base import EmbeddingResult

    result = EmbeddingResult(
        vectors=[[0.1] * 1536],
        model="text-embedding-3-small",
        dim=1536,
        provider="openai",
    )

    with pytest.raises((AttributeError, Exception)):
        # Frozen dataclasses raise FrozenInstanceError (a dataclasses.FrozenInstanceError,
        # subclass of AttributeError). Either subclass is acceptable.
        result.vectors = [[0.2] * 1536]  # type: ignore[misc]


def test_factory_returns_openai_for_default(monkeypatch):
    """With no env override, the factory builds an OpenAI embedder at 1536-d."""
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    from app.config import get_settings
    from app.embeddings.factory import get_embedder

    get_settings.cache_clear()
    embedder = get_embedder()

    assert embedder.provider == "openai"
    assert embedder.model == "text-embedding-3-small"
    assert embedder.dim == 1536


def test_factory_returns_openai_for_large(monkeypatch):
    """``text-embedding-3-large`` resolves to a 3072-d OpenAI embedder."""
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
    from app.config import get_settings
    from app.embeddings.factory import get_embedder

    get_settings.cache_clear()
    embedder = get_embedder()

    assert embedder.provider == "openai"
    assert embedder.model == "text-embedding-3-large"
    assert embedder.dim == 3072


def test_factory_raises_for_voyage(monkeypatch):
    """Voyage backends raise ``NotImplementedError`` mentioning Voyage and Phase 2."""
    monkeypatch.setenv("EMBEDDING_MODEL", "voyage-3-large")
    from app.config import get_settings
    from app.embeddings.factory import get_embedder

    get_settings.cache_clear()
    with pytest.raises(NotImplementedError) as exc:
        get_embedder()

    msg = str(exc.value)
    assert "Voyage" in msg
    assert "Phase 2" in msg


def test_factory_raises_for_local(monkeypatch):
    """``local:`` prefix raises ``NotImplementedError`` — Phase 1 ships OpenAI only."""
    monkeypatch.setenv("EMBEDDING_MODEL", "local:bge-small-en")
    from app.config import get_settings
    from app.embeddings.factory import get_embedder

    get_settings.cache_clear()
    with pytest.raises(NotImplementedError):
        get_embedder()


def test_factory_raises_for_unknown(monkeypatch):
    """Genuinely unknown model names raise ``ValueError`` (not NotImplementedError)."""
    monkeypatch.setenv("EMBEDDING_MODEL", "mystery-model-9000")
    from app.config import get_settings
    from app.embeddings.factory import get_embedder

    get_settings.cache_clear()
    with pytest.raises(ValueError):
        get_embedder()


def test_no_module_imports_openai_outside_openai_embedder():
    """CLAUDE.md hard constraint: only ``app/embeddings/openai_embedder.py`` may import ``openai``.

    This is a regression test against accidental abstraction leaks — if a future
    plan adds ``import openai`` in (e.g.) ``app/retrieval/query.py``, this test
    fails immediately. Threat T-03-01 (Tampering / Abstraction Leak).
    """
    app_dir = Path(__file__).resolve().parent.parent / "app"
    allowed = (app_dir / "embeddings" / "openai_embedder.py").resolve()

    pattern = re.compile(r"^(from openai|import openai)", re.MULTILINE)
    violators: list[str] = []

    for py_file in app_dir.rglob("*.py"):
        if py_file.resolve() == allowed:
            continue
        text = py_file.read_text(encoding="utf-8")
        if pattern.search(text):
            violators.append(str(py_file.relative_to(ROOT)))

    assert violators == [], (
        "Only app/embeddings/openai_embedder.py may import the openai package "
        f"(CLAUDE.md hard constraint). Violators: {violators}"
    )


def test_protocol_has_both_methods():
    """Embedder Protocol must expose embed_documents AND embed_query (separate)."""
    from app.embeddings.base import Embedder

    # The methods are declared as Protocol members; they're present in the class dict.
    assert "embed_documents" in Embedder.__dict__
    assert "embed_query" in Embedder.__dict__
    # And they must NOT be the same callable.
    assert Embedder.__dict__["embed_documents"] is not Embedder.__dict__["embed_query"]
