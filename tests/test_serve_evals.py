# tests/test_serve_evals.py
import json

from fastapi.testclient import TestClient

from merit.serve.app import create_app

SUMMARY = {
    "model": "test-model", "seed": 7, "excluded_rows": 0,
    "arms": {"A": {"agreement": {"mean": 0.95, "ci95": [0.9, 0.99]},
                   "tokens": {"mean": 4257.0, "ci95": [4100.0, 4400.0]},
                   "seconds": {"mean": 6.17, "ci95": [5.2, 7.4]}},
             "B": {"agreement": {"mean": 0.95, "ci95": [0.9, 0.99]},
                   "tokens": {"mean": 4257.0, "ci95": [4100.0, 4400.0]},
                   "seconds": {"mean": 6.12, "ci95": [5.3, 7.0]}}},
    "delta": {"agreement": {"mean": 0.0, "ci95": [0.0, 0.0]},
              "tokens": {"mean": 0.1, "ci95": [-14.0, 14.0]},
              "seconds": {"mean": 0.04, "ci95": [-0.6, 0.9]}},
    "quality_verdict": "parity", "token_overhead": 0.0,
    "token_ceiling_breached": False,
}


def test_evals_renders_summary(tmp_path, monkeypatch):
    p = tmp_path / "summary.json"
    p.write_text(json.dumps(SUMMARY))
    monkeypatch.setenv("MERIT_EVALS_SUMMARY", str(p))
    client = TestClient(create_app())
    r = client.get("/evals")
    assert r.status_code == 200
    assert "parity" in r.text
    assert "LangGraph" in r.text
    assert "4257" in r.text


def test_evals_graceful_without_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIT_EVALS_SUMMARY", str(tmp_path / "missing.json"))
    client = TestClient(create_app())
    r = client.get("/evals")
    assert r.status_code == 200
    assert "sem resultados" in r.text


def test_evals_in_topbar(monkeypatch):
    client = TestClient(create_app())
    assert "4 Evals" in client.get("/fila").text
