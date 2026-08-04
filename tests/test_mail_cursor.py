# tests/test_mail_cursor.py
"""U3 + U4: UID cursor for incremental rescans, and the CLI wiring (--full,
cursor file placement) that drives it."""
import json
from pathlib import Path

from typer.testing import CliRunner

from merit import cli, mail

FIXTURES = Path(__file__).parent / "fixtures" / "mail"
RECRUITER_RAW = (FIXTURES / "recruiter.eml").read_bytes()
NEWSLETTER_RAW = (FIXTURES / "newsletter.eml").read_bytes()

runner = CliRunner()


class _FakeCursorConn:
    """Minimal imaplib.IMAP4_SSL stand-in supporting UID SEARCH/FETCH plus
    response() for UIDVALIDITY - the surface fetch_messages needs in cursor
    mode. Records every call made on it."""

    def __init__(
        self,
        uidvalidity=b"1000",
        search_result=("OK", [b""]),
        fetch_map=None,
        login_ok=True,
        select_result=("OK", [b"1"]),
    ):
        self.calls: list[tuple] = []
        self._uidvalidity = uidvalidity
        self._search_result = search_result
        self._fetch_map = fetch_map or {}
        self._login_ok = login_ok
        self._select_result = select_result

    def login(self, user, password):
        self.calls.append(("login", user, password))
        if not self._login_ok:
            raise mail.imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        return "OK", [b"success"]

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return self._select_result

    def response(self, code):
        self.calls.append(("response", code))
        return "OK", [self._uidvalidity]

    def uid(self, command, *args):
        self.calls.append(("uid", command, *args))
        if command == "SEARCH":
            return self._search_result
        if command == "FETCH":
            num = args[0]
            raw = self._fetch_map.get(num, RECRUITER_RAW)
            return "OK", [(b"1 (BODY[] {%d}" % len(raw), raw), b")"]
        raise AssertionError(f"unexpected uid command: {command}")

    def logout(self):
        self.calls.append(("logout",))


class _FakeConnNoUid:
    """Reproduces the frozen tests/test_mail.py fake shape - no uid()/response()
    at all. fetch_messages must behave identically to the pre-cursor code when
    the conn lacks cursor-mode support (no `merit_cursor` attribute either)."""

    def __init__(self, search_result=(b"1",), fetch_map=None):
        self.calls: list[tuple] = []
        self._search_result = search_result
        self._fetch_map = fetch_map or {}

    def search(self, charset, *criteria):
        self.calls.append(("search", charset, *criteria))
        return "OK", [b" ".join(self._search_result)]

    def fetch(self, num, parts):
        self.calls.append(("fetch", num, parts))
        raw = self._fetch_map.get(num, RECRUITER_RAW)
        return "OK", [(b"1 (BODY[] {%d}" % len(raw), raw), b")"]


def _set_env(monkeypatch, user="someone@example.invalid", mailbox="merit"):
    monkeypatch.setenv("MERIT_IMAP_USER", user)
    monkeypatch.setenv("MERIT_IMAP_PASSWORD", "hunter2-secret")
    monkeypatch.delenv("MERIT_IMAP_HOST", raising=False)
    monkeypatch.setenv("MERIT_IMAP_MAILBOX", mailbox)


def _cursor(conn, path):
    conn.merit_cursor = True
    conn.merit_cursor_path = path
    return conn


# --- fetch_messages(): first run, no cursor file ----------------------------


def test_first_run_no_cursor_searches_all_and_writes_cursor(tmp_path, monkeypatch):
    _set_env(monkeypatch)
    cursor_path = tmp_path / ".last-uid"
    fake = _cursor(
        _FakeCursorConn(
            search_result=("OK", [b"5 7 9"]),
            fetch_map={"5": RECRUITER_RAW, "7": RECRUITER_RAW, "9": RECRUITER_RAW},
        ),
        cursor_path,
    )

    raws = mail.fetch_messages(fake)

    assert len(raws) == 3
    search_calls = [c for c in fake.calls if c[0] == "uid" and c[1] == "SEARCH"]
    assert search_calls == [("uid", "SEARCH", "ALL")]

    record = json.loads(cursor_path.read_text())
    assert record == {
        "host": mail.DEFAULT_HOST,
        "user": "someone@example.invalid",
        "mailbox": "merit",
        "uidvalidity": "1000",
        "uid": 9,
    }


# --- fetch_messages(): second run, unchanged mailbox ------------------------


def test_second_run_unchanged_mailbox_fetches_nothing(tmp_path, monkeypatch):
    _set_env(monkeypatch)
    cursor_path = tmp_path / ".last-uid"
    fake1 = _cursor(
        _FakeCursorConn(search_result=("OK", [b"9"]), fetch_map={"9": RECRUITER_RAW}), cursor_path
    )
    mail.fetch_messages(fake1)

    # server returns the boundary/highest UID for "10:*" even with nothing new
    fake2 = _cursor(_FakeCursorConn(search_result=("OK", [b"9"])), cursor_path)
    raws = mail.fetch_messages(fake2)

    assert raws == []
    search_calls = [c for c in fake2.calls if c[0] == "uid" and c[1] == "SEARCH"]
    assert search_calls == [("uid", "SEARCH", "UID", "10:*")]
    assert not [c for c in fake2.calls if c[0] == "uid" and c[1] == "FETCH"]

    record = json.loads(cursor_path.read_text())
    assert record["uid"] == 9  # never regress below what was already on disk


# --- fetch_messages(): one new message arrives ------------------------------


def test_one_new_message_arrives_fetches_it_and_advances_cursor(tmp_path, monkeypatch):
    _set_env(monkeypatch)
    cursor_path = tmp_path / ".last-uid"
    fake1 = _cursor(
        _FakeCursorConn(search_result=("OK", [b"9"]), fetch_map={"9": RECRUITER_RAW}), cursor_path
    )
    mail.fetch_messages(fake1)

    fake2 = _cursor(
        _FakeCursorConn(search_result=("OK", [b"9 10"]), fetch_map={"10": NEWSLETTER_RAW}),
        cursor_path,
    )
    raws = mail.fetch_messages(fake2)

    assert raws == [NEWSLETTER_RAW]
    fetch_calls = [c for c in fake2.calls if c[0] == "uid" and c[1] == "FETCH"]
    assert fetch_calls == [("uid", "FETCH", "10", "(BODY.PEEK[])")]

    record = json.loads(cursor_path.read_text())
    assert record["uid"] == 10


# --- fetch_messages(): UIDVALIDITY / mailbox / user identity guard ----------


def test_uidvalidity_mismatch_triggers_full_rescan_and_rewrites_cursor(tmp_path, monkeypatch):
    _set_env(monkeypatch)
    cursor_path = tmp_path / ".last-uid"
    fake1 = _cursor(
        _FakeCursorConn(
            uidvalidity=b"1000", search_result=("OK", [b"9"]), fetch_map={"9": RECRUITER_RAW}
        ),
        cursor_path,
    )
    mail.fetch_messages(fake1)

    fake2 = _cursor(
        _FakeCursorConn(
            uidvalidity=b"2000",
            search_result=("OK", [b"3 4"]),
            fetch_map={"3": RECRUITER_RAW, "4": NEWSLETTER_RAW},
        ),
        cursor_path,
    )
    raws = mail.fetch_messages(fake2)

    assert len(raws) == 2
    search_calls = [c for c in fake2.calls if c[0] == "uid" and c[1] == "SEARCH"]
    assert search_calls == [("uid", "SEARCH", "ALL")]  # stale cursor ignored, not a UID range

    record = json.loads(cursor_path.read_text())
    assert record["uidvalidity"] == "2000"
    assert record["uid"] == 4


def test_mailbox_change_triggers_full_rescan(tmp_path, monkeypatch):
    _set_env(monkeypatch, mailbox="merit")
    cursor_path = tmp_path / ".last-uid"
    fake1 = _cursor(
        _FakeCursorConn(search_result=("OK", [b"9"]), fetch_map={"9": RECRUITER_RAW}), cursor_path
    )
    mail.fetch_messages(fake1)

    _set_env(monkeypatch, mailbox="other-box")
    fake2 = _cursor(
        _FakeCursorConn(search_result=("OK", [b"1"]), fetch_map={"1": RECRUITER_RAW}), cursor_path
    )
    raws = mail.fetch_messages(fake2)

    assert len(raws) == 1
    search_calls = [c for c in fake2.calls if c[0] == "uid" and c[1] == "SEARCH"]
    assert search_calls == [("uid", "SEARCH", "ALL")]


def test_user_change_triggers_full_rescan(tmp_path, monkeypatch):
    _set_env(monkeypatch, user="first@example.invalid")
    cursor_path = tmp_path / ".last-uid"
    fake1 = _cursor(
        _FakeCursorConn(search_result=("OK", [b"9"]), fetch_map={"9": RECRUITER_RAW}), cursor_path
    )
    mail.fetch_messages(fake1)

    _set_env(monkeypatch, user="second@example.invalid")
    fake2 = _cursor(
        _FakeCursorConn(search_result=("OK", [b"1"]), fetch_map={"1": RECRUITER_RAW}), cursor_path
    )
    raws = mail.fetch_messages(fake2)

    assert len(raws) == 1
    search_calls = [c for c in fake2.calls if c[0] == "uid" and c[1] == "SEARCH"]
    assert search_calls == [("uid", "SEARCH", "ALL")]


# --- fetch_messages(): corrupt / empty cursor file --------------------------


def test_corrupt_cursor_file_triggers_full_rescan_without_traceback(tmp_path, monkeypatch):
    _set_env(monkeypatch)
    cursor_path = tmp_path / ".last-uid"
    cursor_path.write_text("not valid json {{{", encoding="utf-8")
    fake = _cursor(
        _FakeCursorConn(search_result=("OK", [b"1"]), fetch_map={"1": RECRUITER_RAW}), cursor_path
    )

    raws = mail.fetch_messages(fake)

    assert raws == [RECRUITER_RAW]
    search_calls = [c for c in fake.calls if c[0] == "uid" and c[1] == "SEARCH"]
    assert search_calls == [("uid", "SEARCH", "ALL")]


def test_empty_cursor_file_triggers_full_rescan_without_traceback(tmp_path, monkeypatch):
    _set_env(monkeypatch)
    cursor_path = tmp_path / ".last-uid"
    cursor_path.write_text("", encoding="utf-8")
    fake = _cursor(
        _FakeCursorConn(search_result=("OK", [b"1"]), fetch_map={"1": RECRUITER_RAW}), cursor_path
    )

    raws = mail.fetch_messages(fake)

    assert raws == [RECRUITER_RAW]


# --- fetch_messages(): cursor file write hygiene ----------------------------


def test_cursor_file_written_atomically_with_restricted_permissions(tmp_path, monkeypatch):
    _set_env(monkeypatch)
    cursor_path = tmp_path / ".last-uid"
    fake = _cursor(
        _FakeCursorConn(search_result=("OK", [b"1"]), fetch_map={"1": RECRUITER_RAW}), cursor_path
    )

    mail.fetch_messages(fake)

    assert not list(tmp_path.glob("*.tmp"))
    mode = cursor_path.stat().st_mode
    assert mode & 0o077 == 0


# --- fetch_messages(): regression, no cursor mode ---------------------------


def test_bare_fetch_messages_without_cursor_attrs_behaves_like_before():
    fake = _FakeConnNoUid(search_result=(b"1",), fetch_map={b"1": RECRUITER_RAW})

    raws = mail.fetch_messages(fake)

    assert raws == [RECRUITER_RAW]
    assert not any(c[0] == "uid" for c in fake.calls)


# --- CLI: cursor rides through connect()'s conn ------------------------------


def test_cli_second_run_fetches_no_new_bodies(tmp_path, monkeypatch):
    _set_env(monkeypatch)
    out_dir = tmp_path / "inbox"

    fake1 = _FakeCursorConn(search_result=("OK", [b"5"]), fetch_map={"5": RECRUITER_RAW})
    monkeypatch.setattr(cli, "connect", lambda: fake1)
    result1 = runner.invoke(cli.app, ["ingest-mail", "--out-dir", str(out_dir)])
    assert result1.exit_code == 0, result1.output

    fake2 = _FakeCursorConn(search_result=("OK", [b"5"]))
    monkeypatch.setattr(cli, "connect", lambda: fake2)
    result2 = runner.invoke(cli.app, ["ingest-mail", "--out-dir", str(out_dir)])

    assert result2.exit_code == 0, result2.output
    assert not [c for c in fake2.calls if c[0] == "uid" and c[1] == "FETCH"]
    assert ("logout",) in fake2.calls


def test_cli_full_flag_refetches_everything_and_rewrites_cursor(tmp_path, monkeypatch):
    _set_env(monkeypatch)
    out_dir = tmp_path / "inbox"

    fake1 = _FakeCursorConn(search_result=("OK", [b"5"]), fetch_map={"5": RECRUITER_RAW})
    monkeypatch.setattr(cli, "connect", lambda: fake1)
    runner.invoke(cli.app, ["ingest-mail", "--out-dir", str(out_dir)])

    fake2 = _FakeCursorConn(search_result=("OK", [b"5"]), fetch_map={"5": RECRUITER_RAW})
    monkeypatch.setattr(cli, "connect", lambda: fake2)
    result2 = runner.invoke(cli.app, ["ingest-mail", "--out-dir", str(out_dir), "--full"])

    assert result2.exit_code == 0, result2.output
    search_calls = [c for c in fake2.calls if c[0] == "uid" and c[1] == "SEARCH"]
    assert search_calls == [("uid", "SEARCH", "ALL")]
    fetch_calls = [c for c in fake2.calls if c[0] == "uid" and c[1] == "FETCH"]
    assert fetch_calls == [("uid", "FETCH", "5", "(BODY.PEEK[])")]


def test_cli_select_error_from_connect_exits_1(monkeypatch):
    def raise_select_error():
        raise mail.SelectError("select mailbox 'merit' failed (status='NO')")

    monkeypatch.setattr(cli, "connect", raise_select_error)
    result = runner.invoke(cli.app, ["ingest-mail"])

    assert result.exit_code == 1


def test_cli_search_error_from_fetch_messages_exits_1_and_logs_out(tmp_path, monkeypatch):
    _set_env(monkeypatch)
    out_dir = tmp_path / "inbox"
    fake = _FakeCursorConn(search_result=("NO", [None]))
    monkeypatch.setattr(cli, "connect", lambda: fake)

    result = runner.invoke(cli.app, ["ingest-mail", "--out-dir", str(out_dir)])

    assert result.exit_code == 1
    assert ("logout",) in fake.calls


def test_cli_cursor_file_lives_inside_out_dir(tmp_path, monkeypatch):
    _set_env(monkeypatch)
    out_dir = tmp_path / "inbox"
    fake = _FakeCursorConn(search_result=("OK", [b"1"]), fetch_map={"1": RECRUITER_RAW})
    monkeypatch.setattr(cli, "connect", lambda: fake)

    runner.invoke(cli.app, ["ingest-mail", "--out-dir", str(out_dir)])

    # Cursor is mailbox-scoped since the hourly sync agent (2026-08-03).
    assert (out_dir / ".last-uid-merit").exists()
