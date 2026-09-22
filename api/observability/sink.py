"""The one place errors go. (AC-2)

Client errors and server errors both land here, so "one place" is true whether
or not Sentry is wired up:

    browser  ──POST /api/client-error──┐
                                       ├──► report() ──► Sentry  (SENTRY_DSN set)
    FastAPI unhandled exception ───────┘                └──► stdout JSON (unset)

Following the convention already established in `api/config.py` — a blank key
means fall back to something that still works offline — an unset `SENTRY_DSN`
is not an error. It downgrades the sink to the structured log stream, which is
already collected by Render. CI, tests, and a keyless local run stay green.

The DSN is deliberately server-side only. Routing browser errors through the
API rather than giving the frontend its own public DSN keeps one sink, one
config value, and nothing Sentry-shaped in the client bundle.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from api.observability.redaction import redact

log = logging.getLogger("gamegpt.errors")

_sentry: Any = None


def init_sentry() -> bool:
    """Wire up Sentry if a DSN is present. Returns whether it is active."""
    global _sentry
    dsn = os.environ.get("SENTRY_DSN") or None
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.warning("SENTRY_DSN is set but sentry-sdk is not installed; using log sink")
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
        release=os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT"),
        traces_sample_rate=0.0,  # errors only; tracing is not what this ticket buys
        # Supabase JWTs arrive in Authorization headers and request bodies carry
        # free-text queries. Neither is worth the exposure for a course demo.
        send_default_pii=False,
        max_request_body_size="never",
        before_send=_before_send,
        before_breadcrumb=_before_breadcrumb,
    )
    _sentry = sentry_sdk
    return True


def _before_send(event: dict, hint: dict) -> dict:
    """Last gate before an event leaves the process. (AC-3)"""
    return redact(event)


def _before_breadcrumb(crumb: dict, hint: dict) -> dict | None:
    """Breadcrumbs auto-capture outbound HTTP URLs — including the Steam and
    Gemini calls, whose keys ride in the query string. Scrub, never drop:
    knowing that a Steam call preceded the failure is most of the debugging
    value."""
    return redact(crumb)


def report(
    exc: BaseException | None = None,
    *,
    message: str | None = None,
    **fields: Any,
) -> None:
    """Send one error to the sink, with the current request context attached.

    Safe to call from anywhere; never raises. A sink that can take down the
    request it was reporting on is worse than no sink.
    """
    try:
        if _sentry is not None:
            with _sentry.new_scope() as scope:
                for key, value in redact(fields).items():
                    scope.set_tag(key, value) if isinstance(value, (str, int, bool)) \
                        else scope.set_context(key, {"value": value})
                if exc is not None:
                    _sentry.capture_exception(exc)
                else:
                    _sentry.capture_message(message or "error", level="error")
        # Always log too. Sentry can be down, rate-limited, or not configured,
        # and the log line is the thing a teammate can grep during a demo.
        log.error(message or "unhandled error", exc_info=exc, extra=fields)
    except Exception:  # pragma: no cover - the sink must never be the failure
        logging.getLogger("gamegpt.errors").exception("error sink failed")


def is_active() -> bool:
    return _sentry is not None
