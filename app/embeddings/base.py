"""Embedder protocol + result dataclass.

This module defines the single abstraction the rest of the codebase uses to
embed text. Concrete backends (OpenAI today; Voyage / local later) implement
the ``Embedder`` Protocol and the factory in ``app.embeddings.factory``
dispatches on ``EMBEDDING_MODEL``.

CLAUDE.md hard constraints enforced here:
    1. ``embed_documents()`` and ``embed_query()`` are two distinct methods —
       never conflated. Symmetric providers (OpenAI) collapse the two; asymmetric
       providers (Voyage) need the split. Locking the protocol now means
       Phase 2 can drop in a ``VoyageEmbedder`` without touching the writer or
       the retriever.
    2. ``EmbeddingResult`` is frozen so a returned batch cannot be mutated by
       a caller (defends the input → vector index alignment).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class EmbeddingResult:
    """One batch of embeddings plus the metadata required to validate them.

    Attributes:
        vectors:  One ``list[float]`` per input text, preserved in input order.
        model:    Model identifier (e.g. ``"text-embedding-3-small"``).
        dim:      Dimensionality of every vector. Must match the consuming
                  ``chunks.embedding`` column.
        provider: Backend identifier — ``"openai"`` | ``"voyage"`` | ``"local"``.
    """

    vectors: list[list[float]]
    model: str
    dim: int
    provider: str


@runtime_checkable
class Embedder(Protocol):
    """Two-method embedding contract.

    Symmetric providers may implement ``embed_query`` as
    ``self.embed_documents([text]).vectors[0]``; asymmetric providers (Voyage)
    will set the ``input_type`` parameter differently on each call. Either way
    the call sites stay identical.
    """

    model: str
    dim: int
    provider: str

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        """Embed a batch of corpus passages, preserving input order."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single user query and return its raw vector."""
        ...
