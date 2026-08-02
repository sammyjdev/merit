# tests/test_serve_dossie.py
from fastapi.testclient import TestClient

from merit import track
from merit.serve.app import create_app


def _db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "merit.db")
    monkeypatch.setenv("MERIT_DB", db_path)
    return db_path


def _client():
    return TestClient(create_app())


def test_dossie_index_lists_applications_with_row_contract(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    track.add(db_path, "src.md", title="Backend Engineer", company="Acme")
    client = _client()

    response = client.get("/dossie")

    assert response.status_code == 200
    assert "Backend Engineer" in response.text
    assert "data-row" in response.text
    assert "data-open" in response.text
    assert 'href="/dossie/1"' in response.text


def test_dossie_renders_stepper_jd_thread_notes(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    dossier_root = tmp_path / "applications"
    app_id = track.add(
        db_path,
        "src.md",
        title="Backend Engineer",
        company="Acme",
        status="applied",
        dossier_root=dossier_root,
    )
    dossier_dir = dossier_root / f"{app_id}-backend-engineer"
    (dossier_dir / "jd.md").write_text("# jd\n\nWe need a backend engineer.\n", encoding="utf-8")
    track.log(db_path, app_id, "thread entry one", file="thread")
    track.log(db_path, app_id, "thread entry two", file="thread")
    track.log(db_path, app_id, "thread entry three", file="thread")
    track.log(db_path, app_id, "thread entry four", file="thread")
    track.log(db_path, app_id, "notes entry one", file="notes")
    client = _client()

    response = client.get(f"/dossie/{app_id}")

    assert response.status_code == 200
    text = response.text
    assert 'data-status="applied" data-current="true"' in text
    assert text.count('data-current="true"') == 1
    assert "We need a backend engineer." in text
    # full history, not truncated to the CLI's last-3 window
    assert "thread entry one" in text
    assert "thread entry two" in text
    assert "thread entry three" in text
    assert "thread entry four" in text
    assert "notes entry one" in text


def test_status_change_via_post_updates_row(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    app_id = track.add(db_path, "src.md", title="Backend Engineer", status="applied")
    client = _client()

    response = client.post(f"/dossie/{app_id}/status", data={"status": "screening"})

    assert response.status_code == 200
    assert 'data-status="screening" data-current="true"' in response.text
    with track._conn(db_path) as conn:
        row = conn.execute("SELECT status FROM applications WHERE id = ?", (app_id,)).fetchone()
    assert row["status"] == "screening"


def test_log_post_appends_and_returns_partial(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    app_id = track.add(
        db_path, "src.md", title="Backend Engineer", dossier_root=tmp_path / "applications"
    )
    client = _client()

    response = client.post(
        f"/dossie/{app_id}/log", data={"file": "thread", "text": "recruiter reached out"}
    )

    assert response.status_code == 200
    assert "recruiter reached out" in response.text
    assert "<nav" not in response.text  # partial only, no page shell
    entries = track.entries(db_path, app_id)
    assert any(body == "recruiter reached out" for _, source, body in entries if source == "thread")


def test_log_pasted_entry_header_line_stays_content(tmp_path, monkeypatch):
    # Reuses the phantom-boundary regression from test_track_dossier.py: a
    # pasted line shaped exactly like an entry header must not fabricate a
    # boundary that pushes real entries out of view, now exercised through
    # the HTTP log endpoint + the new track.entries() accessor.
    db_path = _db(tmp_path, monkeypatch)
    app_id = track.add(
        db_path, "src.md", title="Backend Engineer", dossier_root=tmp_path / "applications"
    )
    client = _client()
    poisoned = "before\n## 2026-01-01T00:00:00+00:00\nafter"

    client.post(f"/dossie/{app_id}/log", data={"file": "thread", "text": poisoned})
    client.post(f"/dossie/{app_id}/log", data={"file": "thread", "text": "entry-two"})
    client.post(f"/dossie/{app_id}/log", data={"file": "thread", "text": "entry-three"})

    response = client.get(f"/dossie/{app_id}")

    assert response.status_code == 200
    text = response.text
    assert "before" in text
    assert "after" in text
    assert "entry-two" in text
    assert "entry-three" in text
    thread_entries = [e for e in track.entries(db_path, app_id) if e[1] == "thread"]
    assert len(thread_entries) == 3  # poisoned paste did not fabricate a 4th entry


def test_unknown_id_404s(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    client = _client()

    response = client.get("/dossie/999")

    assert response.status_code == 404


def test_thread_content_is_escaped(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    app_id = track.add(
        db_path, "src.md", title="Backend Engineer", dossier_root=tmp_path / "applications"
    )
    client = _client()

    client.post(f"/dossie/{app_id}/log", data={"file": "thread", "text": "<script>alert(1)</script>"})
    response = client.get(f"/dossie/{app_id}")

    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


def test_legacy_row_without_dossier_shows_placeholder_and_log_creates_it(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    app_id = track.add(db_path, "src.md", title="Backend Engineer")  # no dossier_root: legacy row
    client = _client()

    response = client.get(f"/dossie/{app_id}")
    assert "sem dossie" in response.text

    post_response = client.post(
        f"/dossie/{app_id}/log", data={"file": "thread", "text": "first entry"}
    )

    assert post_response.status_code == 200
    assert "first entry" in post_response.text
    with track._conn(db_path) as conn:
        row = conn.execute("SELECT dossier_dir FROM applications WHERE id = ?", (app_id,)).fetchone()
    assert row["dossier_dir"] is not None
