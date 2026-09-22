"""Observability: structured logging, request context, and one error sink.

Wired in `api/main.py:create_app`. Everything else in the codebase gets the
benefit without importing anything from here — the logging filters read the
request context out of contextvars, so the `log.info` / `log.exception` calls
already in the routers and services gain `request_id` and `user_id` fields
with no edits.
"""

from api.observability.context import (
    auth_source_var,
    current,
    new_request_id,
    request_id_var,
    subject_from_bearer,
    user_id_var,
)
from api.observability.logging_config import configure_logging
from api.observability.middleware import REQUEST_ID_HEADER, install
from api.observability.redaction import is_secret_key, redact, sanitize_url, scrub_text
from api.observability.sink import init_sentry, is_active, report

__all__ = [
    "REQUEST_ID_HEADER",
    "auth_source_var",
    "configure_logging",
    "current",
    "init_sentry",
    "install",
    "is_active",
    "is_secret_key",
    "new_request_id",
    "redact",
    "report",
    "request_id_var",
    "sanitize_url",
    "scrub_text",
    "subject_from_bearer",
    "user_id_var",
]
