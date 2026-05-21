"""Application settings loaded from environment / .env via pydantic-settings.

Field names map automatically to uppercase env vars per pydantic-settings defaults:
    database_url    -> DATABASE_URL
    openai_api_key  -> OPENAI_API_KEY
    embedding_model -> EMBEDDING_MODEL

Use ``get_settings()`` (cached) anywhere you need configuration; never import
``os.getenv`` directly elsewhere in ``app/``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration sourced from environment variables / .env file.

    Notes:
        - ``database_url`` defaults to ``postgresql://localhost:5432/guitar_tone_advisor``
          for local development. Production deployments must override via DATABASE_URL.
        - ``openai_api_key`` is optional in tests / local-only flows; the embedder
          factory will refuse to construct an OpenAI client without it.
        - ``anthropic_api_key`` is optional in tests / local-only flows; the generation
          module refuses to construct AsyncAnthropic without it.
        - ``embedding_model`` defaults to the 1536-d small model that matches the
          ``vector(1536)`` column in ``scripts/init_db.sql`` (D-06).
        - ``debug`` enables EXPLAIN ANALYZE logging in retrieval when ``True``
          (set ``DEBUG=true`` in the environment).
    """

    database_url: str = "postgresql://localhost:5432/guitar_tone_advisor"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    anthropic_model: str = "claude-sonnet-4-6"
    debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide ``Settings`` singleton (cached)."""

    return Settings()
