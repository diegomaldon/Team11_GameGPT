"""Secret scrubbing for anything on its way to a log line or the error sink.

AC-3. Two independent layers, because either one alone has a hole:

  * **Key names** (`redact_mapping`) catch structured data — headers, env dumps,
    a `platform_accounts` row. Cheap and exact, but only works when the secret
    arrives as a labelled field.
  * **Value patterns** (`scrub_text`) catch free text — exception messages,
    stack traces, an f-string a teammate wrote at 2am. Imprecise, but it is the
    only thing standing between a Steam 403 and your API key in Render's logs.

The second layer is not paranoia. `httpx.HTTPStatusError` renders as
``Client error '403 Forbidden' for url 'https://api.steampowered.com/...?key=ABC'``
— the key is in the message, and `log.exception` writes messages.

Everything here is pure and dependency-free so `test_observability.py` can
hammer it offline.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[redacted]"

# ── layer 1: field names ────────────────────────────────────────────────────
# Matched case-insensitively against dict keys, query-string keys, and header
# names. Hyphens and underscores are treated the same so `x-api-key` and
# `x_api_key` both land.
_DENY_KEYS = frozenset(
    {
        "authorization",
        "proxyauthorization",
        "cookie",
        "setcookie",
        "xapikey",
        "apikey",
        "key",
        "token",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "sessiontoken",
        "password",
        "passwordhash",
        "encryptedpassword",
        "secret",
        "clientsecret",
        "dsn",
        "databaseurl",
        "steamapikey",
        "rawgapikey",
        "geminiapikey",
        "anthropicapikey",
        "openaiapikey",
        "supabaseservicerolekey",
        "servicerolekey",
    }
)


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def is_secret_key(key: str) -> bool:
    """True if a field with this name should never have its value logged."""
    return _normalize_key(key) in _DENY_KEYS


# ── layer 2: value shapes ───────────────────────────────────────────────────
# Ordered most-specific first: a Supabase service-role key is a JWT, and we
# would rather the log say [jwt] than nothing, but either is fine. The generic
# 32-hex rule is last because it is the loosest and will occasionally eat an
# innocent hash — an acceptable trade when the alternative is leaking the RAWG
# and Steam keys, both of which are exactly 32 hex characters.
_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Postgres/Supabase DSN — keep host and db, drop the password only.
    (
        re.compile(r"(?P<scheme>postgres(?:ql)?://)(?P<user>[^:/@\s]+):(?P<pw>[^@\s]+)@"),
        r"\g<scheme>\g<user>:[redacted]@",
    ),
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[jwt]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"), "[anthropic-key]"),
    (re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b"), "[gemini-key]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "[openai-key]"),
    (re.compile(r"\bsbp_[a-f0-9]{40}\b"), "[supabase-token]"),
    # Steam keys are 32 uppercase hex; RAWG keys are 32 lowercase hex.
    (re.compile(r"\b[A-Fa-f0-9]{32}\b"), "[hex32]"),
)

_URL_IN_TEXT = re.compile(r"https?://[^\s'\"<>]+")


def sanitize_url(raw: str) -> str:
    """Strip secret-shaped query parameters out of a URL, keeping it readable.

    `?key=ABC&steamid=765...` becomes `?key=[redacted]&steamid=765...` — the
    endpoint and the non-secret parameters survive, which is the whole point:
    a redacted URL is still useful for debugging, an absent one is not.
    """
    try:
        parts = urlsplit(raw)
    except ValueError:
        return "[unparseable-url]"
    if not parts.query:
        return raw
    pairs = [
        (k, REDACTED if is_secret_key(k) else v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(parts._replace(query=urlencode(pairs)))


def scrub_text(text: str) -> str:
    """Remove secrets from free text: URLs first, then bare value shapes."""
    scrubbed = _URL_IN_TEXT.sub(lambda m: sanitize_url(m.group(0)), text)
    for pattern, replacement in _VALUE_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed


def redact(value: Any, _depth: int = 0) -> Any:
    """Recursively scrub a log payload. Applies both layers.

    Depth-capped and length-capped: a log formatter must never be the thing
    that hangs a request, and an unbounded structure in a log line is its own
    kind of outage.
    """
    if _depth > 6:
        return "[max-depth]"
    if isinstance(value, str):
        return scrub_text(value) if len(value) <= 8192 else scrub_text(value[:8192]) + "…"
    if isinstance(value, (int, float, bool, type(None))):
        return value
    if isinstance(value, dict):
        return {
            str(k): REDACTED if is_secret_key(str(k)) else redact(v, _depth + 1)
            for k, v in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple, set)):
        return [redact(v, _depth + 1) for v in list(value)[:100]]
    return scrub_text(repr(value))
