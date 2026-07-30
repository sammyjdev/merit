# tests/test_queue_normalize.py
"""U5 + U6: LinkedIn job-view URL normalization, applied at persistence time,
plus one-time migration of already-normalized-or-not existing queue rows."""
import json

from merit import queue

ALERT_DATE = "2026-07-29"


# --- normalize_url() ---------------------------------------------------------


def test_normalize_url_strips_comm_prefix_and_tracking_params():
    raw = "https://www.linkedin.com/comm/jobs/view/4123456789/?trackingId=aaa111&refId=r1"
    assert queue.normalize_url(raw) == "https://www.linkedin.com/jobs/view/4123456789/"


def test_normalize_url_adds_trailing_slash_when_missing():
    raw = "https://www.linkedin.com/comm/jobs/view/4123456789"
    assert queue.normalize_url(raw) == "https://www.linkedin.com/jobs/view/4123456789/"


def test_normalize_url_leaves_non_matching_url_completely_unchanged():
    raw = "https://www.linkedin.com/feed/update/urn:li:activity:123/"
    assert queue.normalize_url(raw) == raw


def test_normalize_url_preserves_scheme_and_netloc_not_rewritten_to_linkedin():
    raw = "https://x.example/jobs/view/1/"
    assert queue.normalize_url(raw) == raw


# --- dedupe_key() collision with normalize_url() -----------------------------


def test_dedupe_key_of_raw_and_normalized_url_collide():
    raw = "https://www.linkedin.com/comm/jobs/view/4123456789/?trackingId=aaa111&refId=r1"
    assert queue.dedupe_key(raw) == queue.dedupe_key(queue.normalize_url(raw))


# --- append_entries(): new entries get normalized ----------------------------


def _entry(url: str, title: str = "Some Title", company: str | None = "Some Co") -> queue.Entry:
    return queue.Entry(title=title, company=company, url=url, alert_date=ALERT_DATE)


def test_append_entries_writes_normalized_urls_for_new_entries(tmp_path):
    path = tmp_path / "queue.json"
    raw = "https://www.linkedin.com/comm/jobs/view/4123456789/?trackingId=aaa111&refId=r1"

    added = queue.append_entries([_entry(raw)], path)

    assert added[0].url == "https://www.linkedin.com/jobs/view/4123456789/"
    assert queue.load_entries(path) == added


def test_normalized_url_byte_length_shrinks_meaningfully_for_realistic_tracking_href():
    raw = "https://www.linkedin.com/comm/jobs/view/4123456789/?trackingId=abcdef0123456789ghijkl&refId=abcdefgh-1234-5678-90ab-cdef12345678&trk=flagship3_search_srp_jobs"
    normalized = queue.normalize_url(raw)
    assert len(normalized) < 60


# --- migration of a pre-existing legacy queue.json --------------------------


def _write_legacy_file(path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def test_migration_collapses_duplicate_shapes_keeps_first_leaves_other_row_untouched(tmp_path):
    path = tmp_path / "queue.json"
    raw_row = {
        "title": "Raw Tracking Row",
        "company": "Acme",
        "url": "https://www.linkedin.com/comm/jobs/view/555/?trackingId=xxx",
        "alert_date": ALERT_DATE,
        "location": None,
    }
    no_slash_row = {
        "title": "No Slash Row",
        "company": "Acme Dup",
        "url": "https://www.linkedin.com/jobs/view/555",
        "alert_date": ALERT_DATE,
        "location": None,
    }
    other_row = {
        "title": "Unrelated Job",
        "company": "Globex",
        "url": "https://www.linkedin.com/jobs/view/999/",
        "alert_date": "2026-07-01",
        "location": None,
    }
    _write_legacy_file(path, [raw_row, no_slash_row, other_row])

    added = queue.append_entries([], path)

    assert added == []
    rows = queue.load_entries(path)
    assert len(rows) == 2  # the 555-shaped duplicates collapsed into one

    kept_555 = [r for r in rows if "555" in r.url]
    assert len(kept_555) == 1
    assert kept_555[0].title == "Raw Tracking Row"  # file-order-first kept
    assert kept_555[0].url == "https://www.linkedin.com/jobs/view/555/"

    kept_other = next(r for r in rows if "999" in r.url)
    assert kept_other.title == other_row["title"]
    assert kept_other.company == other_row["company"]
    assert kept_other.url == other_row["url"]
    assert kept_other.alert_date == other_row["alert_date"]
    assert kept_other.location == other_row["location"]


def test_migration_second_call_is_a_no_op(tmp_path):
    path = tmp_path / "queue.json"
    _write_legacy_file(
        path,
        [
            {
                "title": "Raw Tracking Row",
                "company": "Acme",
                "url": "https://www.linkedin.com/comm/jobs/view/555/?trackingId=xxx",
                "alert_date": ALERT_DATE,
                "location": None,
            },
            {
                "title": "Unrelated Job",
                "company": "Globex",
                "url": "https://www.linkedin.com/jobs/view/999/",
                "alert_date": "2026-07-01",
                "location": None,
            },
        ],
    )

    queue.append_entries([], path)  # first call performs the migration
    mtime_after_migration = path.stat().st_mtime_ns

    added_second = queue.append_entries([], path)

    assert added_second == []
    assert path.stat().st_mtime_ns == mtime_after_migration


def test_migration_then_new_raw_tracking_url_for_same_job_is_a_duplicate(tmp_path):
    path = tmp_path / "queue.json"
    _write_legacy_file(
        path,
        [
            {
                "title": "Raw Tracking Row",
                "company": "Acme",
                "url": "https://www.linkedin.com/comm/jobs/view/555/?trackingId=xxx",
                "alert_date": ALERT_DATE,
                "location": None,
            }
        ],
    )
    queue.append_entries([], path)  # migrate/normalize first

    new_raw = _entry("https://www.linkedin.com/comm/jobs/view/555/?trackingId=zzz&refId=r9")
    added = queue.append_entries([new_raw], path)

    assert added == []


def test_migration_with_zero_new_alerts_still_triggers_write(tmp_path):
    path = tmp_path / "queue.json"
    _write_legacy_file(
        path,
        [
            {
                "title": "Raw Tracking Row",
                "company": "Acme",
                "url": "https://www.linkedin.com/comm/jobs/view/555/?trackingId=xxx",
                "alert_date": ALERT_DATE,
                "location": None,
            }
        ],
    )

    added = queue.append_entries([], path)

    assert added == []
    rows = queue.load_entries(path)
    assert rows[0].url == "https://www.linkedin.com/jobs/view/555/"


def test_migrated_file_stays_json_array_with_expected_keys_and_permissions(tmp_path):
    path = tmp_path / "queue.json"
    _write_legacy_file(
        path,
        [
            {
                "title": "Raw Tracking Row",
                "company": "Acme",
                "url": "https://www.linkedin.com/comm/jobs/view/555/?trackingId=xxx",
                "alert_date": ALERT_DATE,
                "location": None,
            }
        ],
    )

    queue.append_entries([], path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    for row in raw:
        assert set(row.keys()) == {"title", "company", "url", "alert_date", "location"}
    assert not list(path.parent.glob("*.tmp"))
    mode = path.stat().st_mode
    assert mode & 0o077 == 0
