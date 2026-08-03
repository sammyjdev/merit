# tests/test_serve_vagas.py - unified Vagas view (IA redesign 2026-08-03)
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from merit import queue, track
from merit.serve.app import create_app
from merit.serve.views import vagas

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE_FIXTURE = FIXTURES / "profile_small.yaml"

FRESH_DATE = (date.today() - timedelta(days=3)).isoformat()

INMAIL_STRONG = """---
subject: Senior FastAPI Engineer - Acme
---
# Senior FastAPI Engineer

We need FastAPI and REST APIs experience. FastAPI everywhere.
"""

INMAIL_GAP = """---
subject: PyTorch Researcher - Initech
---
# PyTorch Researcher

Deep PyTorch work only.
"""

ALERT_HOT = queue.Entry(
    title="Senior FastAPI Engineer, REST APIs",
    company="Globex - Brazil (Remote)",
    url="https://x.example/jobs/view/2/",
    alert_date=FRESH_DATE,
)
ALERT_COLD = queue.Entry(
    title="Staff PyTorch Research Engineer",
    company="Initech",
    url="https://x.example/jobs/view/3/",
    alert_date=FRESH_DATE,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "acme.md").write_text(INMAIL_STRONG, encoding="utf-8")
    (inbox / "initech.md").write_text(INMAIL_GAP, encoding="utf-8")
    queue_path = tmp_path / "queue.json"
    queue.append_entries([ALERT_HOT, ALERT_COLD], queue_path)
    monkeypatch.setenv("MERIT_INBOX", str(inbox))
    monkeypatch.setenv("MERIT_QUEUE_PATH", str(queue_path))
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    monkeypatch.setenv("MERIT_PROFILE", str(PROFILE_FIXTURE))
    return TestClient(create_app())


def test_level_bands_are_source_calibrated():
    assert vagas.level("inmail", 12) == "forte"
    assert vagas.level("inmail", 5) == "medio"
    assert vagas.level("inmail", 2) == "fraco"
    assert vagas.level("alerta", 4) == "forte"
    assert vagas.level("alerta", 2) == "medio"
    assert vagas.level("alerta", 0) == "fraco"


def test_bar_is_proportional_and_bounded():
    assert vagas.bar("inmail", 20) == "█" * 5
    assert vagas.bar("inmail", 40) == "█" * 5  # capped
    assert vagas.bar("alerta", 1).count("█") == 1
    assert len(vagas.bar("alerta", 3)) == 5  # filled + empty segments


def test_vagas_lists_both_sources_with_badges(client):
    body = client.get("/vagas").text

    assert "Senior FastAPI Engineer - Acme" in body       # inmail
    assert "Senior FastAPI Engineer, REST APIs" in body   # alert
    assert "inmail" in body
    assert "alerta" in body
    assert "forte" in body


def test_vagas_source_filter(client):
    inmail_only = client.get("/vagas?src=inmail").text
    assert "Senior FastAPI Engineer - Acme" in inmail_only
    assert "REST APIs" not in inmail_only

    alert_only = client.get("/vagas?src=alerta").text
    assert "REST APIs" in alert_only
    assert "Acme" not in alert_only


def test_vagas_hides_weak_by_default_with_counters(client):
    body = client.get("/vagas").text

    assert "PyTorch Researcher" not in body          # inmail score <= 0
    assert "Staff PyTorch Research" not in body      # alert score <= 0
    assert "2 sem aderencia" in body

    revealed = client.get("/vagas?hidden=1").text
    assert "PyTorch Researcher" in revealed
    assert "Staff PyTorch Research" in revealed


def test_vagas_alert_row_links_out_inmail_expands(client):
    body = client.get("/vagas").text

    assert ALERT_HOT.url in body                       # alert opens LinkedIn
    assert "/vagas/posting/acme.md" in body            # inmail lazy detail


def test_vagas_detail_shows_hits_and_sanitized_body(client):
    response = client.get("/vagas/posting/acme.md")

    assert response.status_code == 200
    assert "FastAPI" in response.text
    assert "subject:" not in response.text


def test_vagas_detail_rejects_traversal(client):
    assert client.get("/vagas/posting/..%2facme.md").status_code == 404
    assert client.get("/vagas/posting/nope.md").status_code == 404


def test_vagas_track_inmail_stays_in_list_and_shows_state(client, tmp_path):
    response = client.post(
        "/vagas/track",
        data={"file": "acme.md", "title": "Senior FastAPI Engineer - Acme"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "HX-Redirect" not in response.headers
    listing = track.list_markdown(str(tmp_path / "merit.db"))
    assert "Senior FastAPI Engineer - Acme" in listing

    revealed = client.get("/vagas?hidden=1").text
    assert "queued" in revealed          # pipeline state visible on the row
    assert "/dossie/1" in revealed


def test_vagas_track_alert_by_url(client, tmp_path):
    response = client.post(
        "/vagas/track",
        data={"url": ALERT_HOT.url, "title": ALERT_HOT.title, "company": "Globex"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    listing = track.list_markdown(str(tmp_path / "merit.db"))
    assert "REST APIs" in listing


def test_vagas_discard_inmail_moves_file(client, tmp_path):
    response = client.post("/vagas/discard", data={"file": "acme.md"})

    assert response.status_code == 200
    assert not (tmp_path / "inbox" / "acme.md").exists()
    assert (tmp_path / "inbox" / "discarded" / "acme.md").exists()


def test_vagas_discard_alert_removes_from_queue(client, tmp_path):
    response = client.post("/vagas/discard", data={"url": ALERT_HOT.url})

    assert response.status_code == 200
    remaining = [e.url for e in queue.load_entries(tmp_path / "queue.json")]
    assert ALERT_HOT.url not in remaining


def test_old_routes_redirect_to_vagas(client):
    for old in ("/fila", "/rank", "/"):
        response = client.get(old, follow_redirects=False)
        assert response.status_code in (301, 307, 308)
        assert response.headers["location"] == "/vagas"


def test_topbar_has_four_views_with_badges(client):
    body = client.get("/vagas").text

    assert "1 Vagas (2)" in body      # acme inmail + globex alert visible
    assert "2 Pipeline (0)" in body
    assert "3 Dossie" in body
    assert "4 Evals" in body
    assert "5 Evals" not in body


def test_vagas_caps_rendered_rows(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for i in range(vagas.VAGAS_LIMIT + 10):
        (inbox / f"p-{i:03d}.md").write_text(INMAIL_STRONG, encoding="utf-8")
    monkeypatch.setenv("MERIT_INBOX", str(inbox))
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    monkeypatch.setenv("MERIT_PROFILE", str(PROFILE_FIXTURE))
    client = TestClient(create_app())

    body = client.get("/vagas").text
    assert body.count("data-row") == vagas.VAGAS_LIMIT
    assert "todas" in body


def test_vagas_empty_state(tmp_path, monkeypatch):
    (tmp_path / "inbox").mkdir()
    monkeypatch.setenv("MERIT_INBOX", str(tmp_path / "inbox"))
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    monkeypatch.setenv("MERIT_PROFILE", str(PROFILE_FIXTURE))
    body = TestClient(create_app()).get("/vagas").text

    assert "merit fetch" in body


INMAIL_WITH_THREAD = """---
subject: Staff Engineer - Threadco
---
# Staff Engineer

FastAPI role. Reply: https://www.linkedin.com/messaging/thread/2-TH1==/
"""


def test_vagas_track_inmail_captures_thread_id(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "threadco.md").write_text(INMAIL_WITH_THREAD, encoding="utf-8")
    monkeypatch.setenv("MERIT_INBOX", str(inbox))
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    monkeypatch.setenv("MERIT_PROFILE", str(PROFILE_FIXTURE))
    client = TestClient(create_app())

    client.post(
        "/vagas/track",
        data={"file": "threadco.md", "title": "Staff Engineer - Threadco"},
        follow_redirects=False,
    )

    assert track.threads(str(tmp_path / "merit.db")) == {"2-TH1==": 1}


def test_vagas_groups_inmails_by_thread_keeping_freshest(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    thread = "https://www.linkedin.com/messaging/thread/2-SAME==/"
    (inbox / "old.md").write_text(
        f"---\nsubject: Staff Engineer - Threadco\ndate: Mon, 20 Jul 2026 10:00:00 +0000\n---\n"
        f"# Staff Engineer\n\nFastAPI role. {thread}\n",
        encoding="utf-8",
    )
    (inbox / "new.md").write_text(
        f"---\nsubject: Message replied: Staff Engineer\ndate: Sun, 02 Aug 2026 10:00:00 +0000\n---\n"
        f"# Message replied: Staff Engineer\n\nGreat, FastAPI it is! {thread}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MERIT_INBOX", str(inbox))
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    monkeypatch.setenv("MERIT_PROFILE", str(PROFILE_FIXTURE))
    body = TestClient(create_app()).get("/vagas").text

    assert body.count("data-row") == 1
    assert "Message replied: Staff Engineer" in body   # freshest wins
    assert "1 agrupadas" in body                       # grouping is visible, not silent
