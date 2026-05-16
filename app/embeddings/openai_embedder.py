"""OpenAI implementation of the ``Embedder`` Protocol.

Task 1 ships the minimal constructor surface required for the factory's
default-dispatch tests (it must return an object with ``.provider``,
``.model``, ``.dim`` set correctly). Task 2 fills in ``embed_documents`` +
``embed_query`` with the ``tenacity`` retry wrapper and batch-of-64
slicing per ``.planning/research/STACK.md §Embedding`` and CLAUDE.md.

CLAUDE.md hard constraint: this is the **only** module in ``app/`` that may
import the ``openai`` package — every other call site routes through
``app.embeddings.factory.get_embedder()``.
"""

from __future__ import annotations

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import EmbeddingResult

# Batch size: 64 inputs per ``embeddings.create`` call.
# OpenAI accepts up to 2048 inputs per call but 64 keeps individual requests
# fast and bounded (CONTEXT.md "Claude's Discretion"; STACK.md note #4).
BATCH_SIZE = 64

# Locked dimensionality table — only models Phase 1 supports.
# Keyed exact-match so unknown OpenAI model names raise KeyError loudly.
_DIMS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}


class OpenAIEmbedder:
    """OpenAI-backed embedder. See module docstring for hard constraints."""

    provider = "openai"

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        self.model = model
        # Raises KeyError for any model outside the locked _DIMS table —
        # intentional: an unknown OpenAI model means an unknown column width,
        # and we must NOT silently embed at the wrong dimension.
        self.dim = _DIMS[model]
        # OpenAI 2.x enforces credentials at construction. We route through
        # Settings (loaded from .env / env vars) and fall back to a placeholder
        # so unit tests can construct the embedder offline without an API key
        # (the SDK only contacts the network when ``.embeddings.create`` is
        # called, which our tests mock out). T-03-02 / T-03-03 mitigation: we
        # never log the key and never echo it in exceptions.
        from app.config import get_settings

        api_key = get_settings().openai_api_key or "sk-not-set-construction-only"
        self._client = OpenAI(api_key=api_key)

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(min=1, max=30))
    def embed_documents(self, texts):
        """Embed a corpus batch. Decorated with ``tenacity`` retry/backoff.

        CLAUDE.md hard constraint: all external API calls wrap with
        tenacity. ``stop_after_attempt(5)`` + ``wait_exponential(max=30)``
        bound the total retry budget (T-03-04 mitigation).

        Batching: we slice ``texts`` into groups of ``BATCH_SIZE`` and
        ``extend`` the accumulator in order — the input → vector mapping is
        position-stable (T-03-05 mitigation; test 3 verifies for 130 inputs).
        """
        # Materialize to a list once so len() / slicing are O(1).
        texts_list = list(texts)
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts_list), BATCH_SIZE):
            batch = texts_list[i : i + BATCH_SIZE]
            # STACK.md note #3: do NOT pass dimensions= — we use full native dim.
            resp = self._client.embeddings.create(model=self.model, input=batch)
            all_vectors.extend(d.embedding for d in resp.data)
        return EmbeddingResult(
            vectors=all_vectors,
            model=self.model,
            dim=self.dim,
            provider=self.provider,
        )

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query and return its raw vector.

        CLAUDE.md hard constraint: ``embed_query`` is a DISTINCT method,
        never an alias for ``embed_documents``. OpenAI embeddings are
        symmetric so the call shape is identical, but the split must exist
        for asymmetric providers (Voyage uses ``input_type="query"`` vs
        ``"document"`` at this boundary).
        """
        return self.embed_documents([text]).vectors[0]
