# tests/test_cli_ingest_mail.py
from pathlib import Path

from typer.testing import CliRunner

from merit import cli
from merit.mail import MailError

runner = CliRunner()

RECRUITER_RAW = (
    Path(__file__).parent / "fixtures" / "mail" / "recruiter.eml"
).read_bytes()


class _FakeConn:
    def __init__(self):
        self.logged_out = False

    def logout(self):
        self.logged_out = True


def test_ingest_mail_happy_path_prints_paths_and_counts(tmp_path, monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr(cli, "connect", lambda: fake_conn)
    monkeypatch.setattr(cli, "fetch_messages", lambda conn: [RECRUITER_RAW])

    out_dir = tmp_path / "inbox"
    result = runner.invoke(cli.app, ["ingest-mail", "--out-dir", str(out_dir)])

    assert result.exit_code == 0, result.output
    assert fake_conn.logged_out is True
    md_files = list(out_dir.glob("*.md"))
    assert len(md_files) == 1
    assert str(md_files[0]) in result.output
    assert f"merit match {md_files[0]}" in result.output
    assert "ingested 1, skipped 0" in result.output


def test_ingest_mail_never_echoes_password(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIT_IMAP_PASSWORD", "hunter2-secret")
    fake_conn = _FakeConn()
    monkeypatch.setattr(cli, "connect", lambda: fake_conn)
    monkeypatch.setattr(cli, "fetch_messages", lambda conn: [RECRUITER_RAW])

    out_dir = tmp_path / "inbox"
    result = runner.invoke(cli.app, ["ingest-mail", "--out-dir", str(out_dir)])

    assert "hunter2-secret" not in result.output


def test_ingest_mail_exits_1_on_mail_error_naming_the_var(monkeypatch):
    def raise_mail_error():
        raise MailError("missing required env var MERIT_IMAP_PASSWORD")

    monkeypatch.setattr(cli, "connect", raise_mail_error)

    result = runner.invoke(cli.app, ["ingest-mail"])

    assert result.exit_code == 1
    assert "MERIT_IMAP_PASSWORD" in result.output


def test_ingest_mail_reports_skipped_and_zero_ingested(tmp_path, monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr(cli, "connect", lambda: fake_conn)
    newsletter_raw = (
        Path(__file__).parent / "fixtures" / "mail" / "newsletter.eml"
    ).read_bytes()
    monkeypatch.setattr(cli, "fetch_messages", lambda conn: [newsletter_raw])

    out_dir = tmp_path / "inbox"
    result = runner.invoke(cli.app, ["ingest-mail", "--out-dir", str(out_dir)])

    assert result.exit_code == 0
    assert "ingested 0, skipped 1" in result.output
    assert not list(out_dir.glob("*.md"))


def test_ingest_mail_logs_out_even_if_ingest_raises(tmp_path, monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr(cli, "connect", lambda: fake_conn)
    monkeypatch.setattr(cli, "fetch_messages", lambda conn: [RECRUITER_RAW])

    def boom(raws, out_dir):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "ingest_messages", boom)

    result = runner.invoke(cli.app, ["ingest-mail"])

    assert fake_conn.logged_out is True
    assert result.exit_code != 0


CONV_RAW = (
    b"From: Luana <hit-reply@linkedin.com>\r\n"
    b"Subject: RE: Prompt Engineer\r\n"
    b"Date: Mon, 03 Aug 2026 12:00:00 +0000\r\n"
    b"Message-ID: <conv-1@linkedin.com>\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    b"Oi! Temos retorno do gestor, podemos falar amanha?\r\n"
    b"https://www.linkedin.com/messaging/thread/2-TT99==/\r\n"
)


def test_ingest_mail_routes_replies_of_tracked_threads_to_dossier(tmp_path, monkeypatch):
    from merit import track

    db = tmp_path / "merit.db"
    monkeypatch.setenv("MERIT_DB", str(db))
    app_id = track.add(
        str(db), "corpus/inbox/x.md", title="Prompt Engineer",
        dossier_root=tmp_path / "apps", thread_id="2-TT99==",
    )
    fake_conn = _FakeConn()
    monkeypatch.setattr(cli, "connect", lambda: fake_conn)
    monkeypatch.setattr(cli, "fetch_messages", lambda conn: [CONV_RAW, RECRUITER_RAW])
    out_dir = tmp_path / "inbox"

    result = runner.invoke(cli.app, ["ingest-mail", "--out-dir", str(out_dir)])

    assert result.exit_code == 0, result.output
    assert len(list(out_dir.glob("*.md"))) == 1  # reply did NOT become a posting
    assert "contatos registrados 1" in result.output
    thread_md = next((tmp_path / "apps").rglob("thread.md")).read_text(encoding="utf-8")
    assert "Temos retorno do gestor" in thread_md
    assert "contato recebido" in thread_md
    assert app_id == 1

    # second run: .seen dedups the conversation event
    result2 = runner.invoke(cli.app, ["ingest-mail", "--out-dir", str(out_dir)])
    assert result2.exit_code == 0
    thread_md2 = next((tmp_path / "apps").rglob("thread.md")).read_text(encoding="utf-8")
    assert thread_md2.count("Temos retorno do gestor") == 1


def test_track_backfill_threads_cli(tmp_path, monkeypatch):
    from merit import track

    posting = tmp_path / "vaga.md"
    posting.write_text(
        "# V\nhttps://www.linkedin.com/messaging/thread/2-Q7==/\n", encoding="utf-8"
    )
    db = tmp_path / "merit.db"
    monkeypatch.setenv("MERIT_DB", str(db))
    track.add(str(db), str(posting), title="V")

    result = runner.invoke(cli.app, ["track", "backfill-threads"])

    assert result.exit_code == 0
    assert "1" in result.output
    assert track.threads(str(db)) == {"2-Q7==": 1}
