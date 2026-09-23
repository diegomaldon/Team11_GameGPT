"""Request-scoped observability: the boundary where AC-1 is satisfied.

One middleware sets the context and emits the access line; one exception
handler catches whatever the routers did not. Between them, every request
produces at least one JSON line carrying a request id and a user id, and every
unhandled failure reaches the sink exactly once.
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from api.config import get_settings
from api.observability import context
from api.observability.sink import report

log = logging.getLogger("gamegpt.request")

REQUEST_ID_HEADER = "x-request-id"

# Health checks fire every ~30s on Render and would otherwise be ~95% of the
# log volume on an idle demo service, burying the lines that matter.
_QUIET_PATHS = frozenset({"/api/health"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Accept a caller-supplied id so a browser error and the server request
        # behind it share one key. Cap the length: this string ends up in every
        # log line and is attacker-controlled.
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        request_id = incoming[:64] if incoming else context.new_request_id()

        settings = get_settings()
        subject = context.subject_from_bearer(request.headers.get("authorization"))
        if subject:
            user_id, auth = subject, "jwt-unverified"
        else:
            # No auth layer yet: every router acts as the seeded dev user, so
            # the log should say that rather than imply a real session.
            user_id, auth = settings.dev_user_id, "dev"

        # Set, never reset. uvicorn runs each request in its own asyncio task,
        # and a task copies the context at creation, so these values cannot
        # bleed into another request. Resetting in `finally` would clear them
        # before Starlette's ServerErrorMiddleware — which sits *outside* this
        # middleware but inside the same task — invokes the exception handler,
        # and the resulting error report would lose its request id.
        context.request_id_var.set(request_id)
        context.user_id_var.set(user_id)
        context.auth_source_var.set(auth)
        request.state.request_id = request_id

        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            if request.url.path not in _QUIET_PATHS:
                log.info(
                    "request.complete",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status": status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch anything the routers let through.

    The routers already convert known failures into `HTTPException`s with a
    structured detail; FastAPI handles those itself and they never arrive here.
    What reaches this handler is genuinely unexpected, which is exactly what
    belongs in the error sink.

    The response body carries the request id and nothing else — the client
    needs something to quote back, not a stack trace.
    """
    request_id = getattr(request.state, "request_id", None)
    report(
        exc,
        message="unhandled server exception",
        method=request.method,
        path=request.url.path,
        source="server",
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "Something went wrong. Quote this id if you report it.",
            "request_id": request_id,
        },
        headers={REQUEST_ID_HEADER: request_id} if request_id else None,
    )


def install(app: FastAPI) -> None:
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(Exception, unhandled_exception_handler)
