"""Runtime configuration, read from the environment.

`.env` at the repo root is loaded here (via python-dotenv) so keys land in the
process for every entrypoint — the API, the seed scripts, and tests — without a
manual `export`. Real environment variables always win over `.env` values.

Nothing is hardcoded and no defaults carry secrets. Blank keys are the signal
for services to use their stub/fallback paths so the slice still runs.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel

# override=False: an already-set env var (e.g. an exported DATABASE_URL) wins.
load_dotenv(override=False)


class Settings(BaseModel):
    git_commit: str = "dev"
    dev_user_id: str = "00000000-0000-0000-0000-000000000001"

    database_url: str | None = None

    # LLM generation. Gemini is preferred when set, then Anthropic, then a
    # deterministic offline stub.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"

    # Embeddings run locally via sentence-transformers (Hugging Face) — no key,
    # works offline. 384-dim for all-MiniLM-L6-v2.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

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
        gemini_api_key=_env("GEMINI_API_KEY"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8"),
        embedding_model=os.environ.get(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        ),
        steam_api_key=_env("STEAM_API_KEY"),
        rawg_api_key=_env("RAWG_API_KEY"),
    )
