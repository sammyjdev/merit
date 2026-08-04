# tests/test_serve_pipeline.py
import pytest
from fastapi.testclient import TestClient

from merit import track
from merit.serve.app import create_app


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "merit.db")
    monkeypatch.setenv("MERIT_DB", path)
    return path


@pytest.fixture
def client(db_path):
    return TestClient(create_app())


def test_pipeline_columns_and_counts(client, db_path):
    track.add(db_path, "http://example.com/1", title="App One", company="Company A", status="found")
    track.add(db_path, "http://example.com/2", title="App Two", company="Company B", status="found")
    track.add(db_path, "http://example.com/3", title="App Three", company="Company C", status="queued")

    response = client.get("/pipeline")
    assert response.status_code == 200
    assert "App One" in response.text
    assert "App Two" in response.text
    assert "App Three" in response.text
    assert "encontrada (2)" in response.text


def test_closed_statuses_collapse_into_encerradas(client, db_path):
    track.add(db_path, "http://example.com/1", title="App Found", status="found")
    track.add(db_path, "http://example.com/2", title="App Rejected", status="rejected")
    track.add(db_path, "http://example.com/3", title="App Withdrawn", status="withdrawn")

    response = client.get("/pipeline")
    assert response.status_code == 200
    assert response.text.count("encerradas") == 1
    assert "App Rejected" in response.text
    assert "App Withdrawn" in response.text


def test_move_updates_status_and_returns_board(client, db_path):
    app_id = track.add(db_path, "http://example.com/1", title="App Move", status="found")

    response = client.post(f"/pipeline/{app_id}/move", data={"status": "applied"})
    assert response.status_code == 200
    assert 'id="board"' in response.text

    md = track.list_markdown(db_path)
    assert "| applied |" in md


def test_move_invalid_status_422_named_error(client, db_path):
    app_id = track.add(db_path, "http://example.com/1", title="App Invalid", status="found")

    response = client.post(f"/pipeline/{app_id}/move", data={"status": "not-a-real-status"})
    assert response.status_code == 422
    assert "invalid status" in response.text


def test_cards_have_keyboard_contract_and_dossie_links(client, db_path):
    app_id = track.add(db_path, "http://example.com/1", title="App KB", status="found")

    response = client.get("/pipeline")
    assert response.status_code == 200
    assert "data-row" in response.text
    assert "data-open" in response.text
    assert f'href="/dossie/{app_id}"' in response.text


def test_empty_state(client, db_path):
    response = client.get("/pipeline")
    assert response.status_code == 200
    assert "pipeline vazio - promova vagas na Fila" in response.text


def test_pipeline_cards_show_followup_radar(tmp_path, monkeypatch):
    import sqlite3

    from fastapi.testclient import TestClient

    from merit import track
    from merit.serve.app import create_app

    db = tmp_path / "merit.db"
    monkeypatch.setenv("MERIT_DB", str(db))
    track.add(str(db), "s1", title="Vaga Fria", status="applied")
    track.add(str(db), "s2", title="Vaga Quente", status="applied")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE applications SET updated_at = '2026-07-01T00:00:00+00:00' WHERE id = 1"
        )

    body = TestClient(create_app()).get("/pipeline").text

    assert "sem contato ha" in body
    assert "card-cold" in body                       # >7d highlighted
    assert body.index("Vaga Fria") < body.index("Vaga Quente")  # colder first
