# tests/test_mail_status.py
"""U1 + U2: IMAP status checks, named errors, socket-close-on-failure."""
import pytest

from merit import mail


class _FakeConn:
    """Minimal imaplib.IMAP4_SSL stand-in with controllable (typ, data) returns."""

    def __init__(
        self,
        login_result=("OK", [b"success"]),
        select_result=("OK", [b"1"]),
        search_result=("OK", [b"1"]),
        fetch_result=None,
        logout_raises=False,
    ):
        self.calls: list[tuple] = []
        self._login_result = login_result
        self._select_result = select_result
        self._search_result = search_result
        self._fetch_result = fetch_result or ("OK", [(b"1 (BODY[] {3}", b"raw"), b")"])
        self._logout_raises = logout_raises

    def login(self, user, password):
        self.calls.append(("login", user, password))
        typ, _data = self._login_result
        if typ != "OK":
            raise mail.imaplib.IMAP4.error(f"AUTHENTICATIONFAILED login failed for {password}")
        return self._login_result

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return self._select_result

    def search(self, charset, *criteria):
        self.calls.append(("search", charset, *criteria))
        return self._search_result

    def fetch(self, num, parts):
        self.calls.append(("fetch", num, parts))
        return self._fetch_result

    def logout(self):
        self.calls.append(("logout",))
        if self._logout_raises:
            raise OSError("socket already closed")


def _set_env(monkeypatch):
    monkeypatch.setenv("MERIT_IMAP_USER", "someone@example.invalid")
    monkeypatch.setenv("MERIT_IMAP_PASSWORD", "hunter2-secret")
    monkeypatch.delenv("MERIT_IMAP_HOST", raising=False)
    monkeypatch.delenv("MERIT_IMAP_MAILBOX", raising=False)


# --- connect(): select status ------------------------------------------------


def test_select_no_status_raises_select_error_naming_the_mailbox(monkeypatch):
    _set_env(monkeypatch)
    monkeypatch.setenv("MERIT_IMAP_MAILBOX", "typo-label")
    fake = _FakeConn(select_result=("NO", [b"select failed"]))
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: fake)

    with pytest.raises(mail.SelectError, match="typo-label"):
        mail.connect()


def test_select_malformed_data_raises_select_error(monkeypatch):
    _set_env(monkeypatch)
    fake = _FakeConn(select_result=("OK", [None]))
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: fake)

    with pytest.raises(mail.SelectError):
        mail.connect()


def test_select_error_is_a_mail_error(monkeypatch):
    _set_env(monkeypatch)
    fake = _FakeConn(select_result=("NO", [None]))
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: fake)

    with pytest.raises(mail.MailError):
        mail.connect()


def test_select_failure_closes_the_socket(monkeypatch):
    _set_env(monkeypatch)
    fake = _FakeConn(select_result=("NO", [None]))
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: fake)

    with pytest.raises(mail.SelectError):
        mail.connect()

    assert ("logout",) in fake.calls


# --- connect(): login failure closes socket, preserves __context__ ----------


def test_login_failure_closes_the_socket(monkeypatch):
    _set_env(monkeypatch)
    fake = _FakeConn(login_result=("NO", [b"failed"]))
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: fake)

    with pytest.raises(mail.MailError):
        mail.connect()

    assert ("logout",) in fake.calls


def test_login_failure_preserves_context_invariant(monkeypatch):
    _set_env(monkeypatch)
    fake = _FakeConn(login_result=("NO", [b"failed"]))
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: fake)

    with pytest.raises(mail.MailError) as excinfo:
        mail.connect()

    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_login_failure_message_never_leaks_password(monkeypatch):
    _set_env(monkeypatch)
    fake = _FakeConn(login_result=("NO", [b"failed"]))
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: fake)

    with pytest.raises(mail.MailError) as excinfo:
        mail.connect()

    assert "hunter2-secret" not in str(excinfo.value)


def test_login_failure_with_logout_itself_raising_still_raises_mail_error(monkeypatch):
    _set_env(monkeypatch)
    fake = _FakeConn(login_result=("NO", [b"failed"]), logout_raises=True)
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: fake)

    with pytest.raises(mail.MailError):
        mail.connect()

    assert ("logout",) in fake.calls


# --- fetch_messages(): search status ----------------------------------------


def test_search_no_status_raises_search_error():
    fake = _FakeConn(search_result=("NO", [None]))
    with pytest.raises(mail.SearchError):
        mail.fetch_messages(fake)


def test_search_ok_with_malformed_data_raises_search_error_not_zero_messages():
    # The exact 2026-07-29 masking bug: a malformed-but-"OK" search must not
    # be read as "zero messages".
    fake = _FakeConn(search_result=("OK", [None]))
    with pytest.raises(mail.SearchError):
        mail.fetch_messages(fake)


def test_search_error_is_a_mail_error():
    fake = _FakeConn(search_result=("NO", [None]))
    with pytest.raises(mail.MailError):
        mail.fetch_messages(fake)


def test_search_ok_truly_empty_mailbox_returns_no_messages_and_fetches_nothing():
    fake = _FakeConn(search_result=("OK", [b""]))
    raws = mail.fetch_messages(fake)

    assert raws == []
    assert not [c for c in fake.calls if c[0] == "fetch"]


# --- fetch_messages(): fetch status ------------------------------------------


def test_fetch_no_status_raises_and_does_not_drop_the_body():
    fake = _FakeConn(search_result=("OK", [b"1"]), fetch_result=("NO", [None]))
    with pytest.raises(mail.MailError):
        mail.fetch_messages(fake)
