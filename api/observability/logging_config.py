"""One-JSON-object-per-line logging, with request context and redaction.

AC-1 and AC-3 meet here. Three moving parts, in the order a record passes
through them:

  1. `ContextFilter` stamps request_id / user_id / auth onto every record from
     the contextvars. It is attached to the root handler, so log calls that
     already exist elsewhere in the codebase pick the fields up untouched.
  2. `RedactionFilter` scrubs the formatted message and args.
  3. `JsonFormatter` emits the line, scrubbing once more on the way out —
     belt and braces, because the exception text is only rendered at this
     point and it is the highest-risk field in the record.

Render captures stdout, so `logging.StreamHandler()` is the whole shipping
story. No log files, no rotation, nothing to forget to mount.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

from api.observability import context
from api.observability.redaction import redact, scrub_text

# Attributes LogRecord always carries. Anything outside this set was attached
# by a caller via `extra=` and is worth emitting.
_STANDARD_ATTRS = frozenset(
    """args asctime created exc_info exc_text filename funcName levelname levelno
    lineno message module msecs msg name pathname process processName relativeCreated
    stack_info taskName thread threadName""".split()
)


class ContextFilter(logging.Filter):
    """Attach the current request's identifiers to every record. (AC-1)"""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = context.current()
        # Always set all three, even when null, so the JSON shape is stable and
        # `jq 'select(.request_id == "...")'` never trips over a missing key.
        record.request_id = ctx["request_id"]
        record.user_id = ctx["user_id"]
        record.auth = ctx["auth"]
        return True


class RedactionFilter(logging.Filter):
    """Scrub secrets out of the message and its args before formatting. (AC-3)"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = scrub_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact(record.args)
            else:
                record.args = tuple(redact(a) for a in record.args)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": scrub_text(record.getMessage()),
            "request_id": getattr(record, "request_id", None),
            "user_id": getattr(record, "user_id", None),
            "auth": getattr(record, "auth", None),
        }

        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key not in payload:
                payload[key] = redact(value)

        if record.exc_info:
            payload["error"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                # The single most likely place for a secret to appear. Both
                # message and traceback go through the scrubber.
                "message": scrub_text(str(record.exc_info[1])),
                "stack": scrub_text(self.formatException(record.exc_info)),
            }

        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging() -> None:
    """Install the JSON handler on the root logger. Idempotent.

    `LOG_FORMAT=text` restores stdlib formatting for local work where reading
    raw JSON in a terminal is worse than reading plain lines. The filters stay
    attached either way — redaction is not a production-only concern, since a
    key pasted into a terminal is a key in shell scrollback.
    """
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if os.environ.get("LOG_FORMAT", "json").lower() == "text":
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
    else:
        handler.setFormatter(JsonFormatter())

    handler.addFilter(ContextFilter())
    handler.addFilter(RedactionFilter())

    root.addHandler(handler)
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

    # uvicorn installs its own handlers at startup; clearing them and letting
    # records propagate to root is what gets access logs into the same JSON
    # stream instead of a second, unredacted plain-text one.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    # uvicorn.access logs the raw path; our middleware emits a richer,
    # context-stamped line for the same request, so the duplicate is noise.
    logging.getLogger("uvicorn.access").disabled = True
