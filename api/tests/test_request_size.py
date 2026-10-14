"""Oversized request bodies are refused before they reach a route (TM11-55)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from api.request_size import MAX_REQUEST_BYTES, RequestSizeLimitMiddleware, _content_length
from api.services.library_csv import MAX_CSV_BYTES


class Echo(BaseModel):
    text: str


def _client(max_bytes: int = 100) -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=max_bytes)

    @app.post("/echo")
    async def echo(body: Echo) -> dict:
        return {"length": len(body.text)}

    return TestClient(app)


def test_body_under_the_cap_reaches_the_route():
    resp = _client().post("/echo", json={"text": "short"})
    assert resp.status_code == 200
    assert resp.json() == {"length": 5}


def test_declared_body_over_the_cap_is_refused():
    resp = _client().post("/echo", json={"text": "x" * 200})
    assert resp.status_code == 413
    assert resp.json()["detail"]["error"] == "request_too_large"


def test_chunked_body_over_the_cap_is_refused_while_streaming():
    """No Content-Length: the bytes are counted as they arrive."""

    def chunks():
        for _ in range(10):
            yield b'{"text": "' + b"x" * 50 + b'"}'

    resp = _client().post("/echo", content=chunks(), headers={"content-type": "application/json"})
    assert resp.status_code == 413
    assert resp.json()["detail"]["error"] == "request_too_large"


def test_garbled_content_length_is_ignored_not_trusted():
    """A bad header must not read as "no limit"; the body is then counted instead."""
    assert _content_length({"headers": [(b"content-length", b"12abc")]}) is None
    assert _content_length({"headers": [(b"content-length", "١٢".encode())]}) is None
    assert _content_length({"headers": []}) is None


def test_get_requests_are_untouched():
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=1)

    @app.get("/ping")
    async def ping() -> dict:
        return {"ok": True}

    assert TestClient(app).get("/ping").json() == {"ok": True}


def test_the_real_app_has_the_limit_installed():
    from api.main import create_app

    client = TestClient(create_app())
    resp = client.post(
        "/api/recommend",
        content=b"x" * (MAX_REQUEST_BYTES + 1),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 413


def test_the_real_app_refuses_a_chunked_body_with_413_not_400():
    """The observability middleware wraps `receive` in a task group. If the size
    limit sits outside it, the 413 arrives wrapped and FastAPI turns it into a
    generic 400. Found in a live uvicorn smoke test, not by the unit tests above."""
    from api.main import create_app

    def chunks():
        for _ in range(MAX_REQUEST_BYTES // 100_000 + 2):
            yield b"x" * 100_000

    resp = TestClient(create_app()).post(
        "/api/recommend", content=chunks(), headers={"content-type": "application/json"}
    )
    assert resp.status_code == 413
    assert resp.json()["detail"]["error"] == "request_too_large"


def test_cap_leaves_room_for_the_largest_csv():
    # JSON escaping can roughly double a CSV's size on the wire.
    assert MAX_REQUEST_BYTES >= 2 * MAX_CSV_BYTES
