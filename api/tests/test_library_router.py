"""POST /api/library/sync error contract (TM11-46 AC-02).

AC-02 is "a private profile returns a typed error the UI can explain", so the
typed error has to survive the trip through the service and the router and
arrive at the frontend as something it can branch on. The client-level tests
live in `test_steam_client.py`; this file asserts the HTTP contract the UI
actually consumes.

The service is swapped via FastAPI's dependency-free seam — `routers.library`
constructs `LibrarySyncService()` itself, so the test monkeypatches that name
with a stub that raises. Nothing here touches Steam or a database.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.routers import library as library_router
from api.services.steam_client import (
    SteamError,
    SteamInvalidSteamIDError,
    SteamPermanentError,
    SteamPrivateProfileError,
    SteamTransientError,
)

STEAM_ID = "76561197960287930"


class _RaisingService:
    """Stands in for LibrarySyncService and fails the way the real one would."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def sync(self, *_args, **_kwargs):
        raise self._exc


@pytest.fixture()
def client(monkeypatch):
    from api.main import create_app

    def _install(exc: Exception) -> TestClient:
        monkeypatch.setattr(
            library_router, "LibrarySyncService", lambda *a, **k: _RaisingService(exc)
        )
        return TestClient(create_app(), raise_server_exceptions=False)

    return _install


def _sync(c: TestClient):
    return c.post("/api/library/sync", json={"steam_id": STEAM_ID})


# ───────────── AC-02: the private-profile error reaches the UI ─────────────


def test_private_profile_returns_403_with_an_explainable_body(client):
    resp = _sync(client(SteamPrivateProfileError(STEAM_ID)))
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    # The frontend branches on `error`, never on the prose.
    assert detail["error"] == "steam_profile_private"
    # ...and can render `message` verbatim.
    assert "private" in detail["message"].lower()
    assert "Privacy Settings" in detail["message"]


def test_private_profile_body_leaks_nothing(client):
    """The message is shown to a user, so it must not carry ids, keys or URLs."""
    resp = _sync(client(SteamPrivateProfileError(STEAM_ID)))
    message = resp.json()["detail"]["message"]
    assert STEAM_ID not in message
    assert "http" not in message.lower()


@pytest.mark.parametrize(
    "exc, expected_status, expected_code",
    [
        (SteamPrivateProfileError(STEAM_ID), 403, "steam_profile_private"),
        (SteamInvalidSteamIDError("nope"), 422, "steam_invalid_id"),
        (SteamPermanentError(403, "https://api.steampowered.com/?key=[redacted]"),
         502, "steam_request_rejected"),
        (SteamTransientError("steam down", status_code=503),
         503, "steam_unavailable"),
    ],
)
def test_each_steam_failure_maps_to_its_own_status_and_code(
    client, exc, expected_status, expected_code
):
    """A 4xx means the caller can fix it; a 5xx means retry. The UI needs both."""
    resp = _sync(client(exc))
    assert resp.status_code == expected_status
    assert resp.json()["detail"]["error"] == expected_code


def test_unknown_steam_subclass_still_maps_cleanly(client):
    """A SteamError added later must not fall through to an opaque 500."""

    class FutureSteamError(SteamError):
        pass

    resp = _sync(client(FutureSteamError("something new")))
    assert resp.status_code == 502
    assert resp.json()["detail"]["error"] == "steam_error"


def test_non_steam_failure_is_still_a_generic_502(client):
    """Unrelated bugs keep the old behaviour — no detail leaks out."""
    resp = _sync(client(RuntimeError("psycopg exploded")))
    assert resp.status_code == 502
    assert resp.json()["detail"]["error"] == "sync_failed"
    assert "psycopg" not in resp.text


def test_steam_api_key_never_appears_in_a_response(client):
    """SteamPermanentError carries a URL; the body must not expose a raw key."""
    exc = SteamPermanentError(403, "https://api.steampowered.com/x?key=[redacted]")
    resp = _sync(client(exc))
    assert "key=" not in resp.text
    assert resp.json()["detail"]["message"] == exc.user_message
