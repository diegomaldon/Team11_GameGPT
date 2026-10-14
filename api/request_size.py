"""Reject oversized request bodies before they are read into memory (TM11-55).

FastAPI reads the whole body before any validation runs, so a size check
inside a route or a pydantic max_length comes too late: a 1 GB POST would
already be in memory. This middleware stops it on the way in. A declared
Content-Length is refused up front; a body without one (chunked) is counted as
it arrives.

The cap is for the whole API. The largest legitimate body is a library CSV
(api/services/library_csv.py, 1 MB of text), and JSON escaping can roughly
double that, so 4 MB leaves headroom without letting memory run away.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_REQUEST_BYTES = 4_000_000

_DETAIL = {
    "error": "request_too_large",
    "message": "That upload is too large. The limit is 4 MB.",
}


class RequestSizeLimitMiddleware:
    """ASGI middleware that answers 413 when a request body is over the cap."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared_bytes = _content_length(scope)
        if declared_bytes is not None and declared_bytes > self.max_bytes:
            response = JSONResponse(
                {"detail": _DETAIL}, status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            )
            await response(scope, receive, send)
            return

        received_bytes = 0

        async def counted_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    # FastAPI re-raises an HTTPException thrown while it reads
                    # the body, so this comes back as a 413, not a generic 400.
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=_DETAIL
                    )
            return message

        await self.app(scope, counted_receive, send)


def _content_length(scope: Scope) -> int | None:
    """The declared body size, or None when absent or not a number."""
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            text = value.decode("latin-1").strip()
            return int(text) if text.isascii() and text.isdigit() else None
    return None
