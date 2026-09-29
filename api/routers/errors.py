"""POST /api/client-error — browser errors into the server's error sink. (AC-2)

The frontend has no Sentry DSN of its own on purpose. Sending browser errors
here means one sink, one config value, and no DSN in the client bundle.

This endpoint is unauthenticated by necessity — an error report is most useful
exactly when auth is what broke — so it is treated as hostile input: a small
body cap, a coarse per-IP rate limit, and the same redaction every other log
line gets before anything is written.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from api.observability.redaction import redact, scrub_text
from api.observability.sink import report

router = APIRouter(tags=["errors"])
log = logging.getLogger("gamegpt.client_error")

_WINDOW_SECONDS = 60
_MAX_PER_WINDOW = 20
_hits: dict[str, deque[float]] = defaultdict(deque)


def _rate_limited(client_ip: str) -> bool:
    """In-process sliding window. Resets on deploy and does not span Render
    instances — adequate for a demo, and honest about being a speed bump
    rather than a defence."""
    now = time.monotonic()
    bucket = _hits[client_ip]
    while bucket and now - bucket[0] > _WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _MAX_PER_WINDOW:
        return True
    bucket.append(now)
    if len(_hits) > 1000:  # crude unbounded-growth guard
        for key in [k for k, v in _hits.items() if not v][:500]:
            _hits.pop(key, None)
    return False


class ClientErrorReport(BaseModel):
    message: str = Field(max_length=1000)
    stack: str | None = Field(default=None, max_length=8000)
    kind: str = Field(default="error", max_length=64)
    url: str | None = Field(default=None, max_length=2000)
    user_agent: str | None = Field(default=None, max_length=500)


@router.post("/client-error", status_code=status.HTTP_204_NO_CONTENT)
async def client_error(req: ClientErrorReport, request: Request) -> Response:
    client_ip = request.client.host if request.client else "unknown"
    if _rate_limited(client_ip):
        # 204 either way: a client that is already failing should not have to
        # handle a failure from the endpoint it reports failures to.
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    report(
        message=f"client error: {scrub_text(req.message)}",
        source="client",
        kind=req.kind,
        client_url=redact(req.url),
        client_stack=redact(req.stack),
        user_agent=req.user_agent,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
