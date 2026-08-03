# tests/test_serve_rank.py
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from merit import track
from merit.serve.app import create_app
from merit.serve.views import rank as rank_view

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE_FIXTURE = FIXTURES / "profile_small.yaml"

STRONG_POSTING = """---
subject: Senior FastAPI Engineer - Acme
---
# Senior FastAPI Engineer

We need FastAPI and REST APIs experience.
"""

GAP_POSTING = """---
subject: PyTorch Researcher - Initech
---
# PyTorch Researcher

Deep PyTorch work only.
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "acme.md").write_text(STRONG_POSTING, encoding="utf-8")
    (inbox / "initech.md").write_text(GAP_POSTING, encoding="utf-8")
    monkeypatch.setenv("MERIT_INBOX", str(inbox))
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    monkeypatch.setenv("MERIT_PROFILE", str(PROFILE_FIXTURE))
    return TestClient(create_app())


def test_rank_lists_postings_sorted_by_score(client):
    response = client.get("/rank")

    assert response.status_code == 200
    body = response.text
    assert "Senior FastAPI Engineer - Acme" in body
    assert "PyTorch Researcher - Initech" in body
    assert body.index("Senior FastAPI Engineer") < body.index("PyTorch Researcher")


def test_rank_rows_have_keyboard_contract(client):
    body = client.get("/rank").text

    assert body.count("data-row") == 2
    assert "5 Rank" not in body  # funnel order: rank is view 2
    assert "2 Rank" in body


def test_rank_detail_shows_hit_names_and_body(client):
    response = client.get("/rank/posting/acme.md")

    assert response.status_code == 200
    assert "FastAPI" in response.text
    assert "REST APIs experience" in response.text


def test_rank_detail_strips_mail_frontmatter(client):
    # Raw mail headers (from/date/message-id) are noise in the reading pane.
    response = client.get("/rank/posting/acme.md")

    assert "subject:" not in response.text


def test_rank_detail_rejects_traversal_and_unknown(client):
    assert client.get("/rank/posting/nope.md").status_code == 404
    assert client.get("/rank/posting/..%2facme.md").status_code == 404
    assert client.get("/rank/posting/acme.txt").status_code == 404


def test_rank_track_creates_application_and_redirects(client, tmp_path):
    response = client.post(
        "/rank/track",
        data={"file": "acme.md", "title": "Senior FastAPI Engineer - Acme"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/dossie/1"
    listing = track.list_markdown(str(tmp_path / "merit.db"))
    assert "Senior FastAPI Engineer - Acme" in listing


def test_rank_track_rejects_traversal(client):
    response = client.post(
        "/rank/track",
        data={"file": "../evil.md", "title": "x"},
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_rank_empty_inbox_hints_fetch(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setenv("MERIT_INBOX", str(inbox))
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    monkeypatch.setenv("MERIT_PROFILE", str(PROFILE_FIXTURE))
    body = TestClient(create_app()).get("/rank").text

    assert "merit fetch" in body


def test_rank_caps_rendered_rows_and_shows_remainder(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for i in range(rank_view.RANK_LIMIT + 10):
        (inbox / f"posting-{i:03d}.md").write_text(STRONG_POSTING, encoding="utf-8")
    monkeypatch.setenv("MERIT_INBOX", str(inbox))
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    monkeypatch.setenv("MERIT_PROFILE", str(PROFILE_FIXTURE))
    client = TestClient(create_app())

    body = client.get("/rank").text
    assert body.count("data-row") == rank_view.RANK_LIMIT
    assert "todas (60)" in body

    body_all = client.get("/rank?all=1").text
    assert body_all.count("data-row") == rank_view.RANK_LIMIT + 10


def test_rank_lists_skipped_files(client, tmp_path):
    (tmp_path / "inbox" / "broken.md").write_bytes(b"\xff\xfe invalid")

    body = client.get("/rank").text
    assert "broken.md" in body
