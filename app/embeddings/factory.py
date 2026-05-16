"""Embedder factory — single dispatch point on ``EMBEDDING_MODEL``.

Reading the model name through ``app.config.get_settings()`` (rather than
``os.getenv`` directly) keeps ``.env`` loading behaviour consistent across
the codebase. Tests that need to override the model must call
``get_settings.cache_clear()`` after ``monkeypatch.setenv`` because Settings
is ``@lru_cache``'d.

Phase 1 ships the OpenAI backend only. Voyage and local backends raise
``NotImplementedError`` with a message naming the prefix and the phase that
will implement them — this gives Phase 2 a clean drop-in target. A genuinely
unknown name raises ``ValueError`` so misconfiguration is surfaced loudly.
"""

from __future__ import annotations

from app.config import get_settings


def get_embedder():
    """Return the embedder selected by ``Settings.embedding_model``.

    Returns:
        An object that satisfies the ``app.embeddings.base.Embedder`` Protocol.

    Raises:
        NotImplementedError: if the model prefix names a backend Phase 1 has
            not yet implemented (``voyage-*``, ``local:*``).
        ValueError: if the model name does not match any known prefix.
    """
    model = get_settings().embedding_model

    if model.startswith("text-embedding-3"):
        # Imported lazily so a Voyage-only test environment doesn't need
        # the openai SDK installed to construct its embedder.
        from .openai_embedder import OpenAIEmbedder

        return OpenAIEmbedder(model=model)

    if model.startswith("voyage-"):
        raise NotImplementedError(
            f"Voyage embeddings (model={model!r}) not implemented in Phase 1; "
            "planned for Phase 2."
        )

    if model.startswith("local:"):
        raise NotImplementedError(
            f"Local embeddings (model={model!r}) not implemented in Phase 1."
        )

    raise ValueError(f"Unknown EMBEDDING_MODEL: {model!r}")
