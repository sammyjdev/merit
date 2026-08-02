# tests/test_serve_app.py
from fastapi.testclient import TestClient

from merit import telemetry
from merit.serve import app as serve_app
from merit.serve.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_bind_host_is_localhost_only():
    # The security contract: the serve command must never bind beyond loopback.
    assert serve_app.HOST == "127.0.0.1"


def test_root_redirects_to_fila():
    client = _client()
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/fila"


def test_three_views_render_with_topbar():
    client = _client()
    for path in ("/fila", "/pipeline", "/dossie"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "1 Fila" in response.text
        assert "2 Pipeline" in response.text
        assert "3 Dossie" in response.text


def test_csp_and_nosniff_headers_on_every_response():
    client = _client()
    response = client.get("/fila")
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_api_docs_are_disabled():
    client = _client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_static_assets_served():
    client = _client()
    for asset in ("htmx.min.js", "tokens.css", "app.js"):
        response = client.get(f"/static/{asset}")
        assert response.status_code == 200, asset


def test_create_app_zero_behavior_when_otel_unset(monkeypatch):
    monkeypatch.delenv("MERIT_OTEL", raising=False)
    monkeypatch.setattr(
        telemetry,
        "_load_otel",
        lambda: (_ for _ in ()).throw(AssertionError("_load_otel must not be called")),
    )

    response = TestClient(create_app()).get("/fila")

    assert response.status_code == 200
