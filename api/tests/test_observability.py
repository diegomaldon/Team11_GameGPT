"""Observability tests — evidence for AC-1, AC-2 and AC-3.

AC-3 is the only acceptance criterion on this ticket that can be *proven*
rather than screenshotted, so most of this file is redaction. Every test runs
offline with no DB, no keys and no network, matching the convention in
conftest.py.

Run: `pytest api/tests/test_observability.py -v`
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from api.observability import context
from api.observability.logging_config import ContextFilter, JsonFormatter, RedactionFilter
from api.observability.redaction import is_secret_key, redact, sanitize_url, scrub_text
from api.observability.upstream import UpstreamError, raise_for_status_safe

# Fake credentials shaped like the real ones. None of these are live.
STEAM_KEY = "A1B2C3D4E5F60718293A4B5C6D7E8F90"          # 32 hex, uppercase
RAWG_KEY = "0123456789abcdef0123456789abcdef"            # 32 hex, lowercase
GEMINI_KEY = "AIzaSyD" + "x" * 32                        # AIza + 35 chars
ANTHROPIC_KEY = "sk-ant-api03-" + "z" * 40
SUPABASE_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEyMyJ9.c2lnbmF0dXJl"
DSN = "postgresql://postgres:sup3rs3cr3t@db.abcdefg.supabase.co:5432/postgres"


def _render(record: logging.LogRecord) -> dict:
    """Push a record through the full filter + formatter chain."""
    ContextFilter().filter(record)
    RedactionFilter().filter(record)
    return json.loads(JsonFormatter().format(record))


def _record(msg: str, *args, exc: BaseException | None = None, **extra) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=args or None,
        exc_info=(type(exc), exc, exc.__traceback__) if exc else None,
    )
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


# ── AC-3: key-name redaction ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "key",
    ["authorization", "Authorization", "x-api-key", "X_API_KEY", "apiKey", "key",
     "access_token", "refresh_token", "password", "passwordHash", "DATABASE_URL",
     "STEAM_API_KEY", "service_role_key", "Cookie", "Set-Cookie"],
)
def test_secret_key_names_are_recognised(key):
    assert is_secret_key(key), f"{key} should be treated as secret"


@pytest.mark.parametrize("key", ["user_id", "query_id", "steamid", "title", "rank", "monkey"])
def test_innocent_key_names_survive(key):
    # "monkey" is here on purpose: a substring match on "key" would eat it.
    assert not is_secret_key(key)


def test_nested_mapping_is_redacted():
    row = {
        "user_id": "9c2e",
        "platform_accounts": [{"platform": "steam", "access_token": "ya29.real-token"}],
    }
    out = redact(row)
    assert out["user_id"] == "9c2e"
    assert out["platform_accounts"][0]["access_token"] == "[redacted]"
    assert out["platform_accounts"][0]["platform"] == "steam"


def test_redact_is_depth_and_width_capped():
    deep = cur = {}
    for _ in range(20):
        cur["next"] = {}
        cur = cur["next"]
    assert "[max-depth]" in json.dumps(redact(deep))
    assert len(redact(list(range(500)))) == 100


# ── AC-3: value-shape redaction ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "secret",
    [STEAM_KEY, RAWG_KEY, GEMINI_KEY, ANTHROPIC_KEY, SUPABASE_JWT],
)
def test_bare_secrets_never_survive_scrubbing(secret):
    assert secret not in scrub_text(f"upstream call failed with {secret} in the message")


def test_dsn_password_is_removed_but_host_is_kept():
    out = scrub_text(f"could not connect: {DSN}")
    assert "sup3rs3cr3t" not in out
    assert "db.abcdefg.supabase.co" in out  # still debuggable
    assert "postgres:[redacted]@" in out


def test_url_query_secrets_are_redacted_and_the_rest_survives():
    url = f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={STEAM_KEY}&steamid=76561198000000000&format=json"
    out = sanitize_url(url)
    assert STEAM_KEY not in out
    assert "76561198000000000" in out      # the useful part is preserved
    assert "GetOwnedGames" in out


def test_unparseable_url_does_not_raise():
    assert sanitize_url("http://[::1") == "[unparseable-url]"


# ── AC-3: the specific regression this ticket exists to prevent ─────────────

class _FakeRequest:
    def __init__(self, url):
        self.url = url


class _FakeResponse:
    def __init__(self, status_code, url):
        self.status_code = status_code
        self.request = _FakeRequest(url)


def test_upstream_error_message_has_no_key():
    """httpx.raise_for_status() puts ?key=... in the exception message, which
    routers/library.py then hands to log.exception. raise_for_status_safe must
    not."""
    resp = _FakeResponse(403, f"https://api.steampowered.com/x?key={STEAM_KEY}&steamid=765")
    with pytest.raises(UpstreamError) as exc_info:
        raise_for_status_safe(resp, "steam")
    message = str(exc_info.value)
    assert STEAM_KEY not in message
    assert "403" in message and "steam" in message


def test_upstream_error_passes_through_on_success():
    raise_for_status_safe(_FakeResponse(200, "https://example.com/ok"), "steam")


def test_exception_text_is_scrubbed_in_the_log_line():
    """Even if a future teammate reintroduces a raw raise_for_status, the
    formatter is a second line of defence."""
    try:
        raise RuntimeError(
            f"Client error '403 Forbidden' for url 'https://api.steampowered.com/x?key={STEAM_KEY}'"
        )
    except RuntimeError as exc:
        payload = _render(_record("library sync failed", exc=exc))
    assert STEAM_KEY not in json.dumps(payload)
    assert payload["error"]["type"] == "RuntimeError"


def test_logged_args_and_extras_are_scrubbed():
    payload = _render(
        _record("calling %s", f"https://rawg.io/api/games?key={RAWG_KEY}",
                authorization=f"Bearer {SUPABASE_JWT}")
    )
    blob = json.dumps(payload)
    assert RAWG_KEY not in blob
    assert SUPABASE_JWT not in blob


# ── AC-1: request id and user id on every line ──────────────────────────────

def test_log_line_carries_request_and_user_id():
    context.request_id_var.set("abc123")
    context.user_id_var.set("9c2e-user")
    context.auth_source_var.set("dev")
    payload = _render(_record("request.complete", status=200))
    assert payload["request_id"] == "abc123"
    assert payload["user_id"] == "9c2e-user"
    assert payload["auth"] == "dev"
    assert payload["status"] == 200


def test_fields_are_present_even_when_unset():
    """A stable shape matters more than a compact one: `jq` filters break on
    missing keys."""
    context.request_id_var.set(None)
    context.user_id_var.set(None)
    context.auth_source_var.set(None)
    payload = _render(_record("startup"))
    assert payload["request_id"] is None and "user_id" in payload


def test_subject_is_read_from_a_bearer_token():
    assert context.subject_from_bearer(f"Bearer {SUPABASE_JWT}") == "user-123"


@pytest.mark.parametrize(
    "header", [None, "", "Basic abc", "Bearer not-a-jwt", "Bearer a.b", "Bearer a.!!!.c"]
)
def test_malformed_authorization_headers_do_not_raise(header):
    assert context.subject_from_bearer(header) is None


# ── AC-1 + AC-2 end to end, through the real app ────────────────────────────

@pytest.fixture
def client():
    from api.main import create_app

    app = create_app()

    @app.get("/api/_boom")
    async def _boom():
        raise RuntimeError(f"exploded with {STEAM_KEY}")

    return TestClient(app, raise_server_exceptions=False)


def test_request_id_is_echoed_and_generated(client):
    echoed = client.get("/api/health", headers={"x-request-id": "trace-me-42"})
    assert echoed.headers["x-request-id"] == "trace-me-42"

    generated = client.get("/api/health")
    assert len(generated.headers["x-request-id"]) == 32


def test_unhandled_error_returns_the_id_and_no_secret(client, caplog):
    with caplog.at_level(logging.ERROR):
        resp = client.get("/api/_boom", headers={"x-request-id": "boom-1"})
    assert resp.status_code == 500
    body = resp.json()
    assert body["request_id"] == "boom-1"
    assert STEAM_KEY not in resp.text          # never returned to the caller
    assert "Traceback" not in resp.text        # no stack trace over the wire


def test_client_errors_reach_the_same_sink(client, caplog):
    with caplog.at_level(logging.ERROR):
        resp = client.post(
            "/api/client-error",
            json={"message": "TypeError: undefined is not a function",
                  "stack": "at Foo (page.tsx:12)", "kind": "unhandledrejection"},
            headers={"x-request-id": "shared-id"},
        )
    assert resp.status_code == 204
    assert any("client error" in r.getMessage() for r in caplog.records)


def test_client_error_endpoint_is_rate_limited(client):
    codes = {
        client.post("/api/client-error", json={"message": f"spam {i}"}).status_code
        for i in range(40)
    }
    assert codes == {204}  # never errors back at an already-broken client
