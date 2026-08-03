# tests/test_track.py
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from merit import cli, track

runner = CliRunner()


def _db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "merit.db")
    monkeypatch.setenv("MERIT_DB", db_path)
    return db_path


def test_add_defaults_status_found_and_matches_timestamps(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)

    result = runner.invoke(cli.app, ["track", "add", "https://example.com/job/1"])

    assert result.exit_code == 0, result.output
    assert "added 1" in result.output
    rows = track.list_markdown(db_path)
    assert "found" in rows
    with track._conn(db_path) as conn:
        row = conn.execute("SELECT * FROM applications WHERE id = 1").fetchone()
    assert row["status"] == "found"
    assert row["created_at"] == row["updated_at"]
    assert row["source"] == "https://example.com/job/1"
    assert row["title"] is None
    assert row["company"] is None
    assert row["note"] is None
    assert row["session_id"] is None


def test_add_with_all_options_persists_exactly(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)

    result = runner.invoke(
        cli.app,
        [
            "track",
            "add",
            "postings/acme.md",
            "--title",
            "Backend Engineer",
            "--company",
            "Acme",
            "--status",
            "applied",
            "--note",
            "referred by X",
        ],
    )

    assert result.exit_code == 0, result.output
    with track._conn(db_path) as conn:
        row = conn.execute("SELECT * FROM applications WHERE id = 1").fetchone()
    assert row["id"] == 1
    assert row["source"] == "postings/acme.md"
    assert row["title"] == "Backend Engineer"
    assert row["company"] == "Acme"
    assert row["status"] == "applied"
    assert row["note"] == "referred by X"


def test_add_invalid_status_exits_1_and_inserts_nothing(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)

    result = runner.invoke(
        cli.app, ["track", "add", "src.md", "--status", "bogus"]
    )

    assert result.exit_code == 1
    assert "invalid status" in result.output
    assert "bogus" in result.output
    assert track.list_markdown(db_path) == "no applications"


def test_module_add_invalid_status_raises_track_error(tmp_path):
    db_path = str(tmp_path / "merit.db")

    with pytest.raises(track.TrackError, match="invalid status"):
        track.add(db_path, "src.md", status="bogus")


def test_set_status_updates_note_and_updated_at(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md"])
    with track._conn(db_path) as conn:
        created_at = conn.execute(
            "SELECT created_at FROM applications WHERE id = 1"
        ).fetchone()["created_at"]

    result = runner.invoke(
        cli.app, ["track", "set", "1", "applied", "--note", "sent resume"]
    )

    assert result.exit_code == 0, result.output
    assert "1 -> applied" in result.output
    with track._conn(db_path) as conn:
        row = conn.execute("SELECT * FROM applications WHERE id = 1").fetchone()
    assert row["status"] == "applied"
    assert row["note"] == "sent resume"
    assert row["created_at"] == created_at
    assert datetime.fromisoformat(row["updated_at"]) > datetime.fromisoformat(created_at)


def test_set_status_without_note_preserves_existing_note(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--note", "original note"])

    result = runner.invoke(cli.app, ["track", "set", "1", "applied"])

    assert result.exit_code == 0, result.output
    with track._conn(db_path) as conn:
        row = conn.execute("SELECT note FROM applications WHERE id = 1").fetchone()
    assert row["note"] == "original note"


def test_set_status_only_updates_targeted_row_when_multiple_exist(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "one.md", "--note", "note one"])
    runner.invoke(cli.app, ["track", "add", "two.md", "--note", "note two"])
    with track._conn(db_path) as conn:
        other_before = dict(
            conn.execute("SELECT * FROM applications WHERE id = 2").fetchone()
        )

    result = runner.invoke(
        cli.app, ["track", "set", "1", "applied", "--note", "sent resume"]
    )

    assert result.exit_code == 0, result.output
    with track._conn(db_path) as conn:
        target = dict(conn.execute("SELECT * FROM applications WHERE id = 1").fetchone())
        other_after = dict(
            conn.execute("SELECT * FROM applications WHERE id = 2").fetchone()
        )
    assert target["status"] == "applied"
    assert target["note"] == "sent resume"
    assert other_after == other_before
    assert other_after["status"] == "found"
    assert other_after["note"] == "note two"


def test_set_invalid_status_leaves_row_completely_unchanged(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md"])
    with track._conn(db_path) as conn:
        before = dict(conn.execute("SELECT * FROM applications WHERE id = 1").fetchone())

    result = runner.invoke(cli.app, ["track", "set", "1", "bogus"])

    assert result.exit_code == 1
    assert "invalid status" in result.output
    with track._conn(db_path) as conn:
        after = dict(conn.execute("SELECT * FROM applications WHERE id = 1").fetchone())
    assert after["status"] == before["status"]
    assert after["updated_at"] == before["updated_at"]


def test_set_nonexistent_id_exits_1_and_names_id(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)

    result = runner.invoke(cli.app, ["track", "set", "99", "applied"])

    assert result.exit_code == 1
    assert "no application with id 99" in result.output
    assert track.list_markdown(db_path) == "no applications"


def test_list_markdown_table_ordered_by_id_missing_title_renders_dash(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "one.md", "--title", "One"])
    runner.invoke(cli.app, ["track", "add", "two.md"])
    runner.invoke(cli.app, ["track", "add", "three.md", "--title", "Three"])

    result = runner.invoke(cli.app, ["track", "list"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "| id | title | company | status | updated_at | note |"
    assert lines[1].startswith("|---") or set(lines[1].replace("|", "").strip()) <= {"-", " "}
    body = "\n".join(lines[2:])
    idx_one = body.index("One")
    idx_two = body.index("| 2 |")
    idx_three = body.index("Three")
    assert idx_one < idx_two < idx_three
    assert " - " in lines[3]


def test_list_filters_by_status(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "one.md", "--title", "One", "--status", "found"])
    runner.invoke(
        cli.app, ["track", "add", "two.md", "--title", "Two", "--status", "applied"]
    )

    result = runner.invoke(cli.app, ["track", "list", "--status", "applied"])

    assert result.exit_code == 0, result.output
    assert "Two" in result.output
    assert "One" not in result.output


def test_list_empty_table_prints_no_applications(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)

    result = runner.invoke(cli.app, ["track", "list"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "no applications"
    assert "| id |" not in result.output


def test_timestamps_are_utc_iso_and_recent(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md"])

    with track._conn(db_path) as conn:
        row = conn.execute("SELECT created_at, updated_at FROM applications WHERE id = 1").fetchone()

    now = datetime.now(UTC)
    for value in (row["created_at"], row["updated_at"]):
        assert value.endswith("+00:00")
        parsed = datetime.fromisoformat(value)
        assert abs((now - parsed).total_seconds()) < 60


def test_add_never_touches_network_or_filesystem_for_source(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)

    def boom(*args, **kwargs):
        raise AssertionError("urlopen must not be called")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    missing_path = str(tmp_path / "does-not-exist.md")

    result = runner.invoke(cli.app, ["track", "add", missing_path])

    assert result.exit_code == 0, result.output
    with track._conn(db_path) as conn:
        row = conn.execute("SELECT source FROM applications WHERE id = 1").fetchone()
    assert row["source"] == missing_path


def test_sources_maps_source_to_app_id(tmp_path):
    db = str(tmp_path / "t.db")
    a = track.add(db, "corpus/inbox/a.md", title="A")
    b = track.add(db, "https://x.example/1", title="B")

    assert track.sources(db) == {"corpus/inbox/a.md": a, "https://x.example/1": b}


def test_sources_empty_db(tmp_path):
    assert track.sources(str(tmp_path / "t.db")) == {}


def test_count_active_excludes_terminal_statuses(tmp_path):
    db = str(tmp_path / "t.db")
    track.add(db, "s1", title="A", status="queued")
    track.add(db, "s2", title="B", status="interview")
    rejected = track.add(db, "s3", title="C", status="applied")
    track.set_status(db, rejected, "rejected")

    assert track.count_active(db) == 2
