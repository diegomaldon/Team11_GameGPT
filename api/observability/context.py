"""Per-request context, carried without threading it through every signature.

`contextvars` is the asyncio-safe equivalent of thread-locals: each request
handled by the event loop sees its own values, and a value set in the
middleware is visible to any `await`ed code below it. That is what lets
`logging_config.ContextFilter` stamp request_id and user_id onto log records
emitted by code that knows nothing about this module — including the
`log.info` / `log.exception` calls already in the routers and services.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from contextvars import ContextVar
from typing import Literal

AuthSource = Literal["dev", "jwt-unverified", "anonymous"]

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
auth_source_var: ContextVar[str | None] = ContextVar("auth_source", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex


def current() -> dict[str, str | None]:
    return {
        "request_id": request_id_var.get(),
        "user_id": user_id_var.get(),
        "auth": auth_source_var.get(),
    }


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def subject_from_bearer(header: str | None) -> str | None:
    """Pull the `sub` claim out of a Supabase JWT **without verifying it**.

    For correlation only. The API has no auth layer yet — every router still
    acts as `DEV_USER_ID` — so this value must never be used to decide what a
    caller may read or write. It is logged as `auth: "jwt-unverified"` so a log
    line can never imply an identity check that did not happen.

    Verifying properly means the Supabase JWT secret and a real dependency
    (`PyJWT`), and belongs with the ticket that actually adds authorization.
    """
    if not header or not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        claims = json.loads(_b64url_decode(parts[1]))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    sub = claims.get("sub")
    return str(sub) if isinstance(sub, (str, int)) else None
