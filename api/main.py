"""GameGPT API entrypoint.

Phase 0 ships fake `recommend`/`feedback` behind the real request models so a
public URL exists before any real logic. Later phases replace the router bodies
in place — the app factory, CORS, and health endpoint stay put.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.observability import configure_logging, init_sentry
from api.observability import install as install_observability
from api.routers import errors, feedback, health, recommend

log = logging.getLogger("gamegpt.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the local embedding model in the background so the first real
    # recommend request doesn't pay the ~one-time model-load cost. Non-blocking:
    # boot and the health check return immediately.
    async def _warm() -> None:
        try:
            from api.services.embedding import EmbeddingService

            await EmbeddingService().embed_query("warmup")
            log.info("embedding model warmed")
        except Exception:  # pragma: no cover - best-effort
            pass

    asyncio.create_task(_warm())
    yield

try:  # Wired by Agent C in Phase 2; absent in the Phase 0 slice.
    from api.routers import library  # type: ignore
except Exception:  # pragma: no cover - Phase 0 has no library router yet
    library = None  # type: ignore


def create_app() -> FastAPI:
    # Before anything else: this module runs at import time, so a logging setup
    # placed after this point would miss every startup record.
    configure_logging()
    log.info("error sink: %s", "sentry" if init_sentry() else "structured logs")

    settings = get_settings()
    app = FastAPI(title="GameGPT API", version="0.1.0", lifespan=lifespan)

    # Installed before CORS deliberately. Starlette's add_middleware inserts at
    # the front of the stack, so the *later* call ends up outermost — CORS wraps
    # this, which is what we want: a 500 still comes back with CORS headers, so
    # the browser can read the error instead of reporting an opaque network
    # failure. The request id is still set before any router runs.
    install_observability(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Lets the browser read the id off the response, show it to the user as
        # a "ref", and attach it to a client-error report.
        expose_headers=["x-request-id"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(recommend.router, prefix="/api")
    app.include_router(feedback.router, prefix="/api")
    app.include_router(errors.router, prefix="/api")
    if library is not None:
        app.include_router(library.router, prefix="/api")

    return app


app = create_app()
