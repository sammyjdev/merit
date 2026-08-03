# tests/test_serve_fila.py
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from merit import queue, track
from merit.serve.app import create_app
from merit.serve.views import fila

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE_FIXTURE = FIXTURES / "profile_small.yaml"

FRESH_DATE = (date.today() - timedelta(days=3)).isoformat()

HOT_1 = queue.Entry(
    title="Senior FastAPI Engineer",
    company="Acme",
    url="https://x.example/jobs/view/1/",
    alert_date=FRESH_DATE,
)
HOT_2 = queue.Entry(
    title="Backend Engineer, REST APIs",
    company="Globex",
    url="https://x.example/jobs/view/2/",
    alert_date=FRESH_DATE,
)
COLD = queue.Entry(
    title="Staff PyTorch Research Engineer",
    company="Initech",
    url="https://x.example/jobs/view/3/",
    alert_date=FRESH_DATE,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    queue_path = tmp_path / "queue.json"
    queue.append_entries([HOT_1, HOT_2, COLD], queue_path)
    monkeypatch.setenv("MERIT_QUEUE_PATH", str(queue_path))
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    monkeypatch.setenv("MERIT_PROFILE", str(PROFILE_FIXTURE))
    return TestClient(create_app())


def test_fila_lists_hot_ranked_and_hides_cold_by_default(client):
    response = client.get("/fila")

    assert response.status_code == 200
    body = response.text
    assert "Senior FastAPI Engineer" in body
    assert "Backend Engineer, REST APIs" in body
    assert body.index("Senior FastAPI Engineer") < body.index("Backend Engineer, REST APIs")
    assert "Staff PyTorch Research Engineer" not in body
    assert "1 frias" in body


def test_fila_all_includes_cold(client):
    response = client.get("/fila?hidden=1")

    assert response.status_code == 200
    body = response.text
    assert "Staff PyTorch Research Engineer" in body
    assert body.index("Backend Engineer, REST APIs") < body.index("Staff PyTorch Research Engineer")


def test_discard_removes_from_queue_and_returns_partial(client, tmp_path):
    response = client.post("/fila/discard", data={"url": HOT_1.url})

    assert response.status_code == 200
    assert "Senior FastAPI Engineer" not in response.text
    remaining = queue.load_entries(tmp_path / "queue.json")
    assert len(remaining) == 2
    assert HOT_1.url not in [e.url for e in remaining]


def test_track_keeps_you_in_the_fila(client, tmp_path):
    # Batch triage: acompanhar re-renders the list (no dossier teleport);
    # the tracked entry leaves the default list with a counter.
    response = client.post(
        "/fila/track",
        data={"url": HOT_1.url, "title": HOT_1.title, "company": HOT_1.company},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "HX-Redirect" not in response.headers
    assert "1 acompanhando" in response.text
    listing = track.list_markdown(str(tmp_path / "merit.db"))
    assert "Senior FastAPI Engineer" in listing

    revealed = client.get("/fila?hidden=1").text
    assert "/dossie/1" in revealed


def test_fila_rows_have_keyboard_contract(client):
    response = client.get("/fila")

    body = response.text
    assert body.count("data-row") >= 2
    assert "data-open" in body
    assert 'target="_blank"' in body
    assert 'rel="noopener"' in body


@pytest.fixture
def client_many(tmp_path, monkeypatch):
    queue_path = tmp_path / "queue.json"
    entries = [
        queue.Entry(
            title=f"Senior FastAPI Engineer {i}",
            company="Acme",
            url=f"https://x.example/jobs/view/{i}/",
            alert_date=FRESH_DATE,
        )
        for i in range(fila.FILA_LIMIT + 30)
    ]
    queue.append_entries(entries, queue_path)
    monkeypatch.setenv("MERIT_QUEUE_PATH", str(queue_path))
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    monkeypatch.setenv("MERIT_PROFILE", str(PROFILE_FIXTURE))
    return TestClient(create_app())


def test_fila_caps_rendered_rows_and_shows_remainder(client_many):
    # Integration-wave finding (2026-08-01 live smoke): 3274 hot rows rendered
    # at once. The fila must cap what it renders and say how many more exist.
    response = client_many.get("/fila")
    assert response.status_code == 200
    assert response.text.count("data-row") <= fila.FILA_LIMIT
    assert "mais 30 na fila" in response.text


STALE = queue.Entry(
    title="Senior FastAPI Engineer (old alert)",
    company="Umbrella",
    url="https://x.example/jobs/view/8/",
    alert_date="2026-01-01",
)
ONSITE = queue.Entry(
    title="FastAPI Engineer - On-site Sao Paulo",
    company="Initrode",
    url="https://x.example/jobs/view/9/",
    alert_date="2026-07-29",
)


@pytest.fixture
def client_filters(tmp_path, monkeypatch):
    queue_path = tmp_path / "queue.json"
    queue.append_entries([HOT_1, STALE, ONSITE, COLD], queue_path)
    monkeypatch.setenv("MERIT_QUEUE_PATH", str(queue_path))
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    monkeypatch.setenv("MERIT_PROFILE", str(PROFILE_FIXTURE))
    return TestClient(create_app())


def test_fila_hides_stale_and_onsite_with_counters(client_filters):
    body = client_filters.get("/fila").text

    assert "Senior FastAPI Engineer" in body
    assert "old alert" not in body
    assert "On-site Sao Paulo" not in body
    assert "antigas" not in body  # stale is not even counted
    assert "1 on-site" in body
    assert "1 frias" in body


def test_fila_hidden_toggle_reveals_filtered_but_never_stale(client_filters):
    body = client_filters.get("/fila?hidden=1").text

    assert "old alert" not in body  # owner call 2026-08-03: stale stays out
    assert "On-site Sao Paulo" in body
    assert "Staff PyTorch Research Engineer" in body


def test_fila_detects_onsite_marker_in_company_field(tmp_path, monkeypatch):
    # LinkedIn digests fold location into the company string: "Acme - Sao Paulo, SP (On-site)"
    queue_path = tmp_path / "queue.json"
    queue.append_entries(
        [
            queue.Entry(
                title="Senior FastAPI Engineer",
                company="Acme - Sao Paulo, SP (On-site)",
                url="https://x.example/jobs/view/21/",
                alert_date=FRESH_DATE,
            ),
            queue.Entry(
                title="Senior FastAPI Engineer II",
                company="Globex - Brazil (Remote)",
                url="https://x.example/jobs/view/22/",
                alert_date=FRESH_DATE,
            ),
        ],
        queue_path,
    )
    monkeypatch.setenv("MERIT_QUEUE_PATH", str(queue_path))
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    monkeypatch.setenv("MERIT_PROFILE", str(PROFILE_FIXTURE))
    body = TestClient(create_app()).get("/fila").text

    assert "Senior FastAPI Engineer II" in body
    assert "Sao Paulo, SP (On-site)" not in body
    assert "1 on-site" in body
