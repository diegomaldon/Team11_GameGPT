"""Runtime configuration, read from the environment.

Nothing is hardcoded and no defaults carry secrets. Blank keys are the
signal for services to use their fixture/stub fallbacks so the whole slice
runs with an empty `.env`.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    git_commit: str = "dev"
    dev_user_id: str = "00000000-0000-0000-0000-000000000001"

    database_url: str | None = None

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"

    openai_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"

    steam_api_key: str | None = None
    rawg_api_key: str | None = None

    # CORS origins allowed to call the API in local dev.
    cors_origins: list[str] = ["http://localhost:3000"]

    @property
    def has_db(self) -> bool:
        return bool(self.database_url)


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value or None


@lru_cache
def get_settings() -> Settings:
    return Settings(
        git_commit=os.environ.get("GIT_COMMIT") or _env("RENDER_GIT_COMMIT") or "dev",
        dev_user_id=os.environ.get("DEV_USER_ID", "00000000-0000-0000-0000-000000000001"),
        database_url=_env("DATABASE_URL"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8"),
        openai_api_key=_env("OPENAI_API_KEY"),
        embedding_model=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
        steam_api_key=_env("STEAM_API_KEY"),
        rawg_api_key=_env("RAWG_API_KEY"),
    )
