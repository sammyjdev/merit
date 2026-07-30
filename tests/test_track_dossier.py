# tests/test_track_dossier.py
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from merit import cli, track

runner = CliRunner()


def _mode(path):
    return path.stat().st_mode & 0o777


def _db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "merit.db")
    monkeypatch.setenv("MERIT_DB", db_path)
    return db_path


def test_add_dir_creates_dossier_with_stubs_and_modes(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)

    result = runner.invoke(
        cli.app,
        ["track", "add", "https://example.com/job/1", "--title", "Backend Engineer", "--dir"],
    )

    assert result.exit_code == 0, result.output
    dossier = tmp_path / "applications" / "1-backend-engineer"
    assert dossier.is_dir()
    assert _mode(dossier) == 0o700
    assert _mode(dossier.parent) == 0o700
    for name in ("jd.md", "thread.md", "notes.md"):
        stub = dossier / name
        assert stub.is_file()
        assert _mode(stub) == 0o600


def test_add_dir_stores_dossier_path_on_row(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)

    result = runner.invoke(
        cli.app,
        ["track", "add", "https://example.com/job/1", "--title", "Backend Engineer", "--dir"],
    )

    assert result.exit_code == 0, result.output
    with track._conn(db_path) as conn:
        row = conn.execute("SELECT * FROM applications WHERE id = 1").fetchone()
    expected = str(tmp_path / "applications" / "1-backend-engineer")
    assert row["dossier_dir"] == expected
    assert Path(row["dossier_dir"]).is_dir()


def test_add_dir_slug_prefers_title_then_company_then_source(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)

    runner.invoke(
        cli.app,
        [
            "track", "add", "https://example.com/1",
            "--title", "Backend Engineer", "--company", "Acme", "--dir",
        ],
    )
    runner.invoke(cli.app, ["track", "add", "https://example.com/2", "--company", "Acme", "--dir"])
    runner.invoke(cli.app, ["track", "add", "https://example.com/jobs/staff-widget-engineer", "--dir"])

    names = {p.name for p in (tmp_path / "applications").iterdir()}
    assert "1-backend-engineer" in names
    assert "2-acme" in names
    assert any(n.startswith("3-") for n in names)


def test_add_dir_slug_falls_back_to_application(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)

    result = runner.invoke(cli.app, ["track", "add", "!!!???", "--dir"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "applications" / "1-application").is_dir()


def test_slug_truncates_to_slug_max():
    result = track._slug("A" * 100)

    assert len(result) == 60
    assert not result.endswith("-")


def test_add_without_dir_leaves_dossier_dir_null(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)

    result = runner.invoke(cli.app, ["track", "add", "src.md"])

    assert result.exit_code == 0, result.output
    with track._conn(db_path) as conn:
        row = conn.execute("SELECT * FROM applications WHERE id = 1").fetchone()
    assert row["dossier_dir"] is None
    assert not (tmp_path / "applications").exists()


def test_add_dir_seeds_jd_from_ingested_posting(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    posting = tmp_path / "acme.md"
    posting_content = "---\nfrom: recruiter@acme.com\n---\n\nWe are hiring.\n"
    posting.write_text(posting_content, encoding="utf-8")

    result = runner.invoke(
        cli.app, ["track", "add", str(posting), "--title", "Backend Engineer", "--dir"]
    )

    assert result.exit_code == 0, result.output
    jd = tmp_path / "applications" / "1-backend-engineer" / "jd.md"
    assert jd.read_text(encoding="utf-8") == posting_content
    assert _mode(jd) == 0o600


def test_add_dir_jd_stub_for_url_source_without_network(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)

    def boom(*args, **kwargs):
        raise AssertionError("urlopen must not be called")

    monkeypatch.setattr("urllib.request.urlopen", boom)

    result = runner.invoke(
        cli.app,
        ["track", "add", "https://example.com/jobs/1", "--title", "Backend Engineer", "--dir"],
    )

    assert result.exit_code == 0, result.output
    jd = tmp_path / "applications" / "1-backend-engineer" / "jd.md"
    content = jd.read_text(encoding="utf-8")
    assert "# jd" in content
    assert "https://example.com/jobs/1" in content


def test_add_dir_jd_stub_when_source_file_missing(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    missing = str(tmp_path / "does-not-exist.md")

    result = runner.invoke(cli.app, ["track", "add", missing, "--title", "Backend Engineer", "--dir"])

    assert result.exit_code == 0, result.output
    jd = tmp_path / "applications" / "1-backend-engineer" / "jd.md"
    content = jd.read_text(encoding="utf-8")
    assert "# jd" in content
    assert missing in content


def test_log_appends_iso_utc_stamped_block(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])

    result = runner.invoke(cli.app, ["track", "log", "1", "hello there"])

    assert result.exit_code == 0, result.output
    thread = (tmp_path / "applications" / "1-backend-engineer" / "thread.md").read_text(
        encoding="utf-8"
    )
    matches = list(track._ENTRY_RE.finditer(thread))
    assert len(matches) == 1
    stamp = matches[0].group(1)
    assert stamp.endswith("+00:00")
    assert abs((datetime.now(UTC) - datetime.fromisoformat(stamp)).total_seconds()) < 60
    assert "hello there" in thread


def test_log_appends_second_entry_keeping_the_first(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    runner.invoke(cli.app, ["track", "log", "1", "first message"])

    result = runner.invoke(cli.app, ["track", "log", "1", "second message"])

    assert result.exit_code == 0, result.output
    thread = (tmp_path / "applications" / "1-backend-engineer" / "thread.md").read_text(
        encoding="utf-8"
    )
    assert "first message" in thread
    assert "second message" in thread
    assert thread.index("first message") < thread.index("second message")
    assert len(list(track._ENTRY_RE.finditer(thread))) == 2


def test_log_stdin_dash_ingests_whole_recruiter_message(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    message = "Hi Sam,\n\nWe have an opening for a Staff Engineer.\n\nBest,\nRecruiter"

    result = runner.invoke(cli.app, ["track", "log", "1", "--file", "thread", "-"], input=message)

    assert result.exit_code == 0, result.output
    thread = (tmp_path / "applications" / "1-backend-engineer" / "thread.md").read_text(
        encoding="utf-8"
    )
    assert "We have an opening for a Staff Engineer." in thread
    assert "Recruiter" in thread
    assert "\n\n" in thread


def test_log_defaults_to_thread_file(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    dossier = tmp_path / "applications" / "1-backend-engineer"
    notes_before = (dossier / "notes.md").read_bytes()

    result = runner.invoke(cli.app, ["track", "log", "1", "no file flag"])

    assert result.exit_code == 0, result.output
    assert "no file flag" in (dossier / "thread.md").read_text(encoding="utf-8")
    assert (dossier / "notes.md").read_bytes() == notes_before


def test_log_notes_file_only_touches_notes(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    dossier = tmp_path / "applications" / "1-backend-engineer"
    thread_before = (dossier / "thread.md").read_bytes()

    result = runner.invoke(cli.app, ["track", "log", "1", "--file", "notes", "a private note"])

    assert result.exit_code == 0, result.output
    assert "a private note" in (dossier / "notes.md").read_text(encoding="utf-8")
    assert (dossier / "thread.md").read_bytes() == thread_before


def test_log_invalid_file_exits_1_and_writes_nothing(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    dossier = tmp_path / "applications" / "1-backend-engineer"
    before = {p.name: p.read_bytes() for p in dossier.iterdir()}

    result = runner.invoke(cli.app, ["track", "log", "1", "--file", "jd", "irrelevant"])

    assert result.exit_code == 1
    assert "invalid file" in result.output
    after = {p.name: p.read_bytes() for p in dossier.iterdir()}
    assert after == before


def test_log_nonexistent_id_exits_1_and_creates_nothing(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)

    result = runner.invoke(cli.app, ["track", "log", "99", "hello"])

    assert result.exit_code == 1
    assert "no application with id 99" in result.output
    assert not (tmp_path / "applications").exists()


def test_log_empty_stdin_exits_1_and_appends_nothing(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    dossier = tmp_path / "applications" / "1-backend-engineer"
    thread_before = (dossier / "thread.md").read_bytes()

    result = runner.invoke(cli.app, ["track", "log", "1", "-"], input="\n   \n")

    assert result.exit_code == 1
    assert "empty log entry" in result.output
    assert (dossier / "thread.md").read_bytes() == thread_before


def test_log_on_row_without_dossier_creates_and_records_it(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer"])

    result = runner.invoke(cli.app, ["track", "log", "1", "legacy log entry"])

    assert result.exit_code == 0, result.output
    dossier = tmp_path / "applications" / "1-backend-engineer"
    assert dossier.is_dir()
    assert _mode(dossier) == 0o700
    assert "legacy log entry" in (dossier / "thread.md").read_text(encoding="utf-8")
    with track._conn(db_path) as conn:
        row = conn.execute("SELECT dossier_dir FROM applications WHERE id = 1").fetchone()
    assert row["dossier_dir"] == str(dossier)


def test_module_log_without_dossier_root_raises(tmp_path):
    db_path = str(tmp_path / "merit.db")
    track.add(db_path, "src.md", title="Backend Engineer")

    with pytest.raises(track.TrackError, match="no dossier"):
        track.log(db_path, 1, "hello")

    assert not (tmp_path / "applications").exists()


def test_log_preserves_preexisting_thread_content(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    dossier = tmp_path / "applications" / "1-backend-engineer"
    (dossier / "thread.md").write_text("# thread\n\nhand written note\n", encoding="utf-8")

    result = runner.invoke(cli.app, ["track", "log", "1", "new entry"])

    assert result.exit_code == 0, result.output
    thread = (dossier / "thread.md").read_text(encoding="utf-8")
    assert "hand written note" in thread
    assert "new entry" in thread
    assert thread.index("hand written note") < thread.index("new entry")
    assert _mode(dossier / "thread.md") == 0o600


def test_log_only_touches_the_target_dossier(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "one.md", "--title", "Backend Engineer", "--dir"])
    runner.invoke(cli.app, ["track", "add", "two.md", "--title", "Frontend Engineer", "--dir"])
    dossier2 = tmp_path / "applications" / "2-frontend-engineer"
    snapshot = {p.name: p.read_bytes() for p in dossier2.iterdir()}
    with track._conn(db_path) as conn:
        dossier2_before = conn.execute(
            "SELECT dossier_dir FROM applications WHERE id = 2"
        ).fetchone()["dossier_dir"]

    result = runner.invoke(cli.app, ["track", "log", "1", "only for app one"])

    assert result.exit_code == 0, result.output
    after = {p.name: p.read_bytes() for p in dossier2.iterdir()}
    assert after == snapshot
    with track._conn(db_path) as conn:
        dossier2_after = conn.execute(
            "SELECT dossier_dir FROM applications WHERE id = 2"
        ).fetchone()["dossier_dir"]
    assert dossier2_after == dossier2_before
    dossier1 = tmp_path / "applications" / "1-backend-engineer"
    assert "only for app one" in (dossier1 / "thread.md").read_text(encoding="utf-8")


def test_log_restores_dossier_mode_when_loosened(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    dossier = tmp_path / "applications" / "1-backend-engineer"
    dossier.chmod(0o755)

    result = runner.invoke(cli.app, ["track", "log", "1", "re-tighten"])

    assert result.exit_code == 0, result.output
    assert _mode(dossier) == 0o700


def test_show_renders_row_fields_dossier_and_entry(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(
        cli.app,
        [
            "track", "add", "corpus/inbox/posting.md",
            "--title", "Backend Engineer", "--company", "Acme",
            "--status", "applied", "--note", "referred by X", "--dir",
        ],
    )
    runner.invoke(cli.app, ["track", "log", "1", "Hi Sam, we have an opening for..."])

    result = runner.invoke(cli.app, ["track", "show", "1"])

    assert result.exit_code == 0, result.output
    output = result.output
    assert "id: 1" in output
    assert "title: Backend Engineer" in output
    assert "company: Acme" in output
    assert "status: applied" in output
    assert "source: corpus/inbox/posting.md" in output
    assert "note: referred by X" in output
    dossier = str(tmp_path / "applications" / "1-backend-engineer")
    assert f"dossier: {dossier}" in output
    assert "files: jd.md, notes.md, thread.md" in output
    assert "last 3 log entries:" in output
    assert "Hi Sam, we have an opening for..." in output


def test_show_legacy_row_renders_dashes_and_none(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer"])

    result = runner.invoke(cli.app, ["track", "show", "1"])

    assert result.exit_code == 0, result.output
    assert "dossier: -" in result.output
    assert "files: -" in result.output
    assert "none" in result.output


def test_show_with_deleted_dossier_dir_does_not_crash(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    dossier = tmp_path / "applications" / "1-backend-engineer"
    shutil.rmtree(dossier)

    result = runner.invoke(cli.app, ["track", "show", "1"])

    assert result.exit_code == 0, result.output
    assert "files: -" in result.output
    assert "none" in result.output


def test_show_lists_last_three_entries_chronologically(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    for i in range(1, 6):
        runner.invoke(cli.app, ["track", "log", "1", f"entry-{i}"])

    result = runner.invoke(cli.app, ["track", "show", "1"])

    assert result.exit_code == 0, result.output
    output = result.output
    assert "entry-1" not in output
    assert "entry-2" not in output
    assert "entry-3" in output
    assert "entry-4" in output
    assert "entry-5" in output
    assert output.index("entry-3") < output.index("entry-4") < output.index("entry-5")


def test_show_merges_thread_and_notes_entries_by_recency(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    runner.invoke(cli.app, ["track", "log", "1", "thread body text"])
    runner.invoke(cli.app, ["track", "log", "1", "--file", "notes", "notes body text"])

    result = runner.invoke(cli.app, ["track", "show", "1"])

    assert result.exit_code == 0, result.output
    assert "thread body text" in result.output
    assert "notes body text" in result.output
    assert "(thread)" in result.output
    assert "(notes)" in result.output


def test_show_notes_only_dossier_renders_latest_notes_entry(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    runner.invoke(cli.app, ["track", "log", "1", "--file", "notes", "notes-only entry"])

    result = runner.invoke(cli.app, ["track", "show", "1"])

    assert result.exit_code == 0, result.output
    assert "notes-only entry" in result.output
    assert "(notes)" in result.output
    assert "none" not in result.output


def test_show_interleaves_thread_and_notes_last_three_overall(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    dossier = tmp_path / "applications" / "1-backend-engineer"
    (dossier / "thread.md").write_text(
        "# thread\n"
        "\n## 2026-01-01T00:00:01+00:00\n\nthread-oldest\n"
        "\n## 2026-01-01T00:00:03+00:00\n\nthread-newer\n",
        encoding="utf-8",
    )
    (dossier / "notes.md").write_text(
        "# notes\n"
        "\n## 2026-01-01T00:00:02+00:00\n\nnotes-older\n"
        "\n## 2026-01-01T00:00:04+00:00\n\nnotes-newest\n",
        encoding="utf-8",
    )

    result = runner.invoke(cli.app, ["track", "show", "1"])

    assert result.exit_code == 0, result.output
    output = result.output
    assert "thread-oldest" not in output
    assert "notes-older" in output
    assert "thread-newer" in output
    assert "notes-newest" in output
    assert output.index("notes-older") < output.index("thread-newer") < output.index("notes-newest")


def test_show_nonexistent_id_exits_1(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)

    result = runner.invoke(cli.app, ["track", "show", "99"])

    assert result.exit_code == 1
    assert "no application with id 99" in result.output


def test_entries_parser_ignores_non_timestamp_headings():
    text = (
        "\n## 2026-07-30T14:02:11.481932+00:00\n\n"
        "line one\n## Not a timestamp\nline two\n"
    )

    entries = track._entries(text)

    assert len(entries) == 1
    stamp, body = entries[0]
    assert stamp == "2026-07-30T14:02:11.481932+00:00"
    assert "## Not a timestamp" in body


_LEGACY_CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS applications (
        id         INTEGER PRIMARY KEY,
        source     TEXT NOT NULL,
        title      TEXT,
        company    TEXT,
        status     TEXT NOT NULL,
        note       TEXT,
        session_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
"""


def test_migration_adds_dossier_dir_to_legacy_db(tmp_path):
    db_path = str(tmp_path / "merit.db")
    raw = sqlite3.connect(db_path)
    raw.execute(_LEGACY_CREATE_TABLE_SQL)
    raw.execute(
        "INSERT INTO applications "
        "(source, title, company, status, note, session_id, created_at, updated_at) "
        "VALUES ('src.md', 'Backend Engineer', 'Acme', 'found', NULL, NULL, 'x', 'x')"
    )
    raw.commit()
    raw.close()

    with track._conn(db_path) as conn:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(applications)")}
        row = conn.execute("SELECT * FROM applications WHERE id = 1").fetchone()

    assert "dossier_dir" in columns
    assert row["source"] == "src.md"
    assert row["dossier_dir"] is None

    path = track.log(db_path, 1, "post-migration entry", dossier_root=tmp_path / "applications")

    assert path.read_text(encoding="utf-8").count("post-migration entry") == 1


def test_fresh_db_has_dossier_dir_as_last_column(tmp_path):
    db_path = str(tmp_path / "merit.db")

    with track._conn(db_path) as conn:
        names = [r["name"] for r in conn.execute("PRAGMA table_info(applications)")]

    assert names[-1] == "dossier_dir"


def test_set_status_preserves_dossier_dir(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])

    result = runner.invoke(cli.app, ["track", "set", "1", "applied"])

    assert result.exit_code == 0, result.output
    with track._conn(db_path) as conn:
        row = conn.execute("SELECT dossier_dir FROM applications WHERE id = 1").fetchone()
    expected = str(tmp_path / "applications" / "1-backend-engineer")
    assert row["dossier_dir"] == expected


def test_track_module_imports_no_merit_siblings():
    source = Path(track.__file__).read_text(encoding="utf-8")

    assert "from merit" not in source
    assert "import merit" not in source


def test_dossier_root_derives_from_db_parent(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "sub" / "merit.db"))

    assert cli._dossier_root() == tmp_path / "sub" / "applications"


def test_pasted_line_matching_entry_header_does_not_fabricate_an_entry(tmp_path, monkeypatch):
    # Reviewer-reproduced bug (issue #15, round 3): a pasted recruiter message
    # containing a line shaped exactly like an entry header became a phantom
    # boundary. With 3 real entries, the phantom made 4, pushing the first
    # real entry out of the last-3 window.
    _db(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["track", "add", "src.md", "--title", "Backend Engineer", "--dir"])
    poisoned = "before\n## 2026-01-01T00:00:00+00:00\nafter"
    runner.invoke(cli.app, ["track", "log", "1", poisoned])
    runner.invoke(cli.app, ["track", "log", "1", "entry-two"])
    runner.invoke(cli.app, ["track", "log", "1", "entry-three"])

    result = runner.invoke(cli.app, ["track", "show", "1"])

    assert result.exit_code == 0, result.output
    # The poisoned message is ONE entry: with 3 real entries total, all of it
    # stays inside the last-3 window. On the broken code "before" is pushed out.
    assert "before" in result.output
    # "after" is the phantom entry's body on broken code; sorted by its fake
    # old stamp it falls outside the last-3 window and vanishes entirely.
    assert "after" in result.output
    assert "entry-two" in result.output
    assert "entry-three" in result.output
