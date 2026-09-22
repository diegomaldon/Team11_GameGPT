"""Safe error raising for outbound HTTP calls. (AC-3)

`httpx`'s own `raise_for_status()` builds a message containing the full request
URL. Two of our three outbound calls put an API key in the query string —
Steam (`?key=`) and Gemini (`?key=`) — so that message is a secret, and it
reaches `log.exception` in the routers above. `scrub_text` in the log formatter
catches it as a backstop, but the right fix is not to construct the string in
the first place.

Use `raise_for_status_safe(resp, "steam")` instead of `resp.raise_for_status()`
anywhere the request may carry credentials.
"""

from __future__ import annotations

from typing import Any

from api.observability.redaction import sanitize_url


class UpstreamError(RuntimeError):
    """A non-2xx from an external service, described without leaking the key."""

    def __init__(self, service: str, status_code: int, url: str) -> None:
        self.service = service
        self.status_code = status_code
        self.url = url
        super().__init__(f"{service} returned HTTP {status_code} for {url}")


def raise_for_status_safe(resp: Any, service: str) -> None:
    if 200 <= resp.status_code < 300:
        return
    raise UpstreamError(service, resp.status_code, sanitize_url(str(resp.request.url)))
