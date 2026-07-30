# tests/test_cli_queue.py
from pathlib import Path

from typer.testing import CliRunner

from merit import cli, queue

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures" / "mail"
RECRUITER_RAW = (FIXTURES / "recruiter.eml").read_bytes()
JOB_ALERT_RAW = (FIXTURES / "job_alert.eml").read_bytes()
PROFILE_FIXTURE = str(Path(__file__).parent / "fixtures" / "profile_small.yaml")

HOT_ENTRY = queue.Entry(
    title="Senior Backend Engineer, REST APIs",
    company="Acme Corp",
    url="https://x.example/jobs/view/1/",
    alert_date="2026-07-29",
)
COLD_ENTRY = queue.Entry(
    title="Staff PyTorch Research Engineer",
    company="Globex Industries",
    url="https://x.example/jobs/view/2/",
    alert_date="2026-07-29",
)


class _FakeConn:
    def __init__(self):
        self.logged_out = False

    def logout(self):
        self.logged_out = True


def test_queue_lists_hot_entries_first(tmp_path):
    queue_path = tmp_path / "queue.json"
    queue.append_entries([HOT_ENTRY, COLD_ENTRY], queue_path)

    result = runner.invoke(
        cli.app, ["queue", "--queue-path", str(queue_path), "--profile", PROFILE_FIXTURE]
    )

    assert result.exit_code == 0, result.output
    assert "Senior Backend Engineer, REST APIs" in result.output
    assert "Acme Corp" in result.output
    assert HOT_ENTRY.url in result.output
    hot_pos = result.output.index("Senior Backend Engineer, REST APIs")
    assert "Staff PyTorch Research Engineer" not in result.output[:hot_pos]


def test_queue_hides_cold_entries_by_default(tmp_path):
    queue_path = tmp_path / "queue.json"
    queue.append_entries([HOT_ENTRY, COLD_ENTRY], queue_path)

    result = runner.invoke(
        cli.app, ["queue", "--queue-path", str(queue_path), "--profile", PROFILE_FIXTURE]
    )

    assert "Staff PyTorch Research Engineer" not in result.output


def test_queue_all_flag_includes_cold_entries(tmp_path):
    queue_path = tmp_path / "queue.json"
    queue.append_entries([HOT_ENTRY, COLD_ENTRY], queue_path)

    result = runner.invoke(
        cli.app,
        ["queue", "--queue-path", str(queue_path), "--profile", PROFILE_FIXTURE, "--all"],
    )

    assert "Staff PyTorch Research Engineer" in result.output
    assert "Globex Industries" in result.output


def test_queue_empty_file_is_friendly_not_a_traceback(tmp_path):
    queue_path = tmp_path / "missing-queue.json"

    result = runner.invoke(
        cli.app, ["queue", "--queue-path", str(queue_path), "--profile", PROFILE_FIXTURE]
    )

    assert result.exit_code == 0
    assert result.exception is None
    assert "Traceback" not in result.output
    assert "No queued postings yet" in result.output


def test_queue_prints_honest_limitation_with_match_stdin_hint(tmp_path):
    queue_path = tmp_path / "queue.json"
    queue.append_entries([HOT_ENTRY], queue_path)

    result = runner.invoke(
        cli.app, ["queue", "--queue-path", str(queue_path), "--profile", PROFILE_FIXTURE]
    )

    assert "merit match -" in result.output


def test_ingest_mail_also_queues_job_alerts(tmp_path, monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr(cli, "connect", lambda: fake_conn)
    monkeypatch.setattr(cli, "fetch_messages", lambda conn: [RECRUITER_RAW, JOB_ALERT_RAW])

    out_dir = tmp_path / "inbox"
    queue_path = tmp_path / "queue.json"
    result = runner.invoke(
        cli.app,
        [
            "ingest-mail",
            "--out-dir",
            str(out_dir),
            "--queue-path",
            str(queue_path),
        ],
    )

    assert result.exit_code == 0, result.output
    md_files = list(out_dir.glob("*.md"))
    assert len(md_files) == 1
    entries = queue.load_entries(queue_path)
    assert len(entries) == 2


def test_ingest_mail_prints_queue_hint_and_count(tmp_path, monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr(cli, "connect", lambda: fake_conn)
    monkeypatch.setattr(cli, "fetch_messages", lambda conn: [JOB_ALERT_RAW])

    out_dir = tmp_path / "inbox"
    queue_path = tmp_path / "queue.json"
    result = runner.invoke(
        cli.app,
        [
            "ingest-mail",
            "--out-dir",
            str(out_dir),
            "--queue-path",
            str(queue_path),
        ],
    )

    assert "queued 2" in result.output
    assert "merit queue" in result.output


def test_ingest_mail_recruiter_only_writes_no_queue_file(tmp_path, monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr(cli, "connect", lambda: fake_conn)
    monkeypatch.setattr(cli, "fetch_messages", lambda conn: [RECRUITER_RAW])

    out_dir = tmp_path / "inbox"
    queue_path = tmp_path / "queue.json"
    result = runner.invoke(
        cli.app,
        [
            "ingest-mail",
            "--out-dir",
            str(out_dir),
            "--queue-path",
            str(queue_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert not queue_path.exists()
