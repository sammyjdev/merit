# tests/test_queue.py
import json
from pathlib import Path

from merit import queue
from merit.profile import load_profile, strong_terms

FIXTURES = Path(__file__).parent / "fixtures" / "mail"
JOB_ALERT_RAW = (FIXTURES / "job_alert.eml").read_bytes()
PROFILE_FIXTURE = Path(__file__).parent / "fixtures" / "profile_small.yaml"

ALERT_DATE = "2026-07-29"


def _fixture_html() -> str:
    import email
    import email.policy

    msg = email.message_from_bytes(JOB_ALERT_RAW, policy=email.policy.default)
    return msg.get_body(preferencelist=("html",)).get_content()


def _fixture_entries() -> list[queue.Entry]:
    return queue.parse_alert(_fixture_html(), ALERT_DATE)


# --- parse_alert() ---------------------------------------------------------


def test_parse_alert_extracts_three_entries_with_correct_fields():
    entries = _fixture_entries()

    assert len(entries) == 3
    assert entries[0] == queue.Entry(
        title="Senior Backend Engineer, REST APIs",
        company="Acme Corp",
        url="https://www.linkedin.com/comm/jobs/view/4123456789/?trackingId=aaa111&refId=r1",
        alert_date=ALERT_DATE,
    )
    assert entries[1] == queue.Entry(
        title="Staff PyTorch Research Engineer",
        company="Globex Industries",
        url="https://www.linkedin.com/comm/jobs/view/4987654321/?trackingId=bbb222&refId=r2",
        alert_date=ALERT_DATE,
    )
    assert entries[2].url == entries[0].url


def test_parse_alert_ignores_non_job_anchors():
    entries = _fixture_entries()
    titles = [e.title for e in entries]

    assert len(entries) == 3
    assert "See all 25 jobs" not in titles
    assert "Unsubscribe" not in titles


def test_parse_alert_skips_anchor_without_title():
    html = '<a href="https://x.example/jobs/view/1/"></a><p>Some Co</p>'
    assert queue.parse_alert(html, ALERT_DATE) == []


def test_parse_alert_rejects_non_https_href():
    html = '<a href="javascript:alert(1)//jobs/view/1/">Fake Title</a><p>Some Co</p>'
    assert queue.parse_alert(html, ALERT_DATE) == []


def test_parse_alert_strips_control_characters_from_fields():
    html = '<a href="https://x.example/jobs/view/1/">\x1b[31mRed Title\x1b[0m</a><p>Some Co</p>'
    entries = queue.parse_alert(html, ALERT_DATE)

    assert len(entries) == 1
    assert entries[0].title == "[31mRed Title[0m"
    assert "\x1b" not in entries[0].title


def test_parse_alert_strips_control_characters_from_url():
    html = (
        '<a href="https://x.example/jobs/view/1/?x=\x1b[31mfoo">Title</a><p>Some Co</p>'
    )
    entries = queue.parse_alert(html, ALERT_DATE)

    assert len(entries) == 1
    assert "\x1b" not in entries[0].url
    assert entries[0].url == "https://x.example/jobs/view/1/?x=[31mfoo"


def test_parse_alert_location_is_always_none():
    entries = _fixture_entries()
    assert all(e.location is None for e in entries)


# --- is_hot() ---------------------------------------------------------------


def test_is_hot_matches_strong_alias_case_insensitively():
    assert queue.is_hot("Senior Backend Engineer, REST APIs", ["fastapi", "rest apis"]) is True
    assert queue.is_hot("Senior Backend Engineer, rest apis", ["fastapi", "REST APIs"]) is True


def test_is_hot_is_cold_for_non_strong_skill_name():
    assert queue.is_hot("Staff PyTorch Research Engineer", ["fastapi", "rest apis"]) is False


def test_prefilter_split_matches_fixture_profile():
    profile = load_profile(PROFILE_FIXTURE)
    terms = strong_terms(profile)
    entries = _fixture_entries()

    assert queue.is_hot(entries[0].title, terms) is True
    assert queue.is_hot(entries[1].title, terms) is False
    assert queue.is_hot(entries[2].title, terms) is True


def test_queue_module_imports_no_llm_layer():
    import ast

    src = Path(queue.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any(name.startswith("merit") for name in imported)


# --- load_entries() / append_entries() --------------------------------------


def test_load_entries_missing_file_returns_empty(tmp_path):
    assert queue.load_entries(tmp_path / "missing.json") == []


def test_append_entries_dedupes_within_batch_by_url(tmp_path):
    path = tmp_path / "queue.json"
    entries = _fixture_entries()

    added = queue.append_entries(entries, path)

    assert len(added) == 2
    assert queue.load_entries(path) == added


def test_append_entries_dedupes_against_existing_file(tmp_path):
    path = tmp_path / "queue.json"
    entries = _fixture_entries()
    queue.append_entries(entries, path)

    added_again = queue.append_entries(entries, path)

    assert added_again == []
    assert len(queue.load_entries(path)) == 2


def test_dedupe_key_ignores_tracking_query_params():
    a = "https://www.linkedin.com/comm/jobs/view/123/?trackingId=aaa"
    b = "https://www.linkedin.com/comm/jobs/view/123/?trackingId=zzz&refId=r9"
    assert queue.dedupe_key(a) == queue.dedupe_key(b)


def test_append_entries_returns_only_new_entries(tmp_path):
    path = tmp_path / "queue.json"
    old = queue.Entry(title="Old", company="Old Co", url="https://x.example/jobs/view/1/", alert_date=ALERT_DATE)
    new = queue.Entry(title="New", company="New Co", url="https://x.example/jobs/view/2/", alert_date=ALERT_DATE)
    queue.append_entries([old], path)

    added = queue.append_entries([old, new], path)

    assert added == [new]


def test_append_entries_preserves_insertion_order(tmp_path):
    path = tmp_path / "queue.json"
    first = queue.Entry(title="First", company=None, url="https://x.example/jobs/view/1/", alert_date=ALERT_DATE)
    second = queue.Entry(title="Second", company=None, url="https://x.example/jobs/view/2/", alert_date=ALERT_DATE)
    queue.append_entries([first], path)
    queue.append_entries([second], path)

    rows = queue.load_entries(path)
    assert [r.title for r in rows] == ["First", "Second"]


def test_queue_file_is_json_array_with_expected_keys(tmp_path):
    path = tmp_path / "queue.json"
    queue.append_entries(_fixture_entries(), path)

    raw = json.loads(path.read_text(encoding="utf-8"))

    assert isinstance(raw, list)
    assert len(raw) == 2
    for row in raw:
        assert set(row.keys()) == {"title", "company", "url", "alert_date", "location"}


def test_queue_write_is_atomic_and_leaves_no_tmp_file(tmp_path):
    path = tmp_path / "queue.json"
    queue.append_entries(_fixture_entries(), path)

    assert not list(tmp_path.glob("*.tmp"))
    mode = path.stat().st_mode
    assert mode & 0o077 == 0
