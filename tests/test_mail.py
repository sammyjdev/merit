# tests/test_mail.py
import email
import email.policy
import hashlib
from pathlib import Path

import pytest

from merit import mail

FIXTURES = Path(__file__).parent / "fixtures" / "mail"
RECRUITER_RAW = (FIXTURES / "recruiter.eml").read_bytes()
NEWSLETTER_RAW = (FIXTURES / "newsletter.eml").read_bytes()
JOB_ALERT_DIGEST_RAW = (FIXTURES / "job_alert.eml").read_bytes()

PLAIN_ONLY_SENTENCE = (
    "This role directly matches your background in distributed retrieval systems."
)
SHARED_SENTENCE = "We are hiring a Senior AI Engineer to work on retrieval pipelines."


def _lookalike_domain_raw() -> bytes:
    return (
        b"From: Fake Recruiter <spam@evil-linkedin.com>\r\n"
        b"Subject: Alex sent you a message\r\n"
        b"Date: Tue, 28 Jul 2026 09:14:00 +0000\r\n"
        b"Message-ID: <lookalike-0001@evil-linkedin.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Hello, click here.\r\n"
    )


def _job_alert_raw() -> bytes:
    return (
        b"From: LinkedIn Job Alerts <jobs-noreply@linkedin.com>\r\n"
        b"Subject: 25 new jobs match your search\r\n"
        b"Date: Tue, 28 Jul 2026 09:14:00 +0000\r\n"
        b"Message-ID: <jobalert-0001@mail.linkedin.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"New jobs are available for your saved search.\r\n"
    )


def _no_message_id_raw() -> bytes:
    return (
        b"From: LinkedIn <messages-noreply@linkedin.com>\r\n"
        b"Subject: New message from Jordan\r\n"
        b"Date: Tue, 28 Jul 2026 09:14:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"We have a great opportunity for you.\r\n"
    )


def _no_date_raw() -> bytes:
    return (
        b"From: LinkedIn <messages-noreply@linkedin.com>\r\n"
        b"Subject: Jordan sent you a message\r\n"
        b"Message-ID: <nodate-0001@mail.linkedin.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"We have a great opportunity for you.\r\n"
    )


def _bad_raw() -> bytes:
    # Not valid enough to parse cleanly under strict use, but email.message_from_bytes
    # is lenient; use something that raises inside our own processing instead:
    # a From header value that is present but whose recruiter-check still runs fine.
    # We simulate a hard failure via monkeypatching in the dedicated test instead.
    return b"garbage not really an email"


class _FakeConn:
    """Minimal imaplib.IMAP4_SSL stand-in; records every call made on it."""

    def __init__(self, search_result=(b"1",), fetch_map=None, login_ok=True):
        self.calls: list[tuple] = []
        self._search_result = search_result
        self._fetch_map = fetch_map or {}
        self._login_ok = login_ok
        self.debug = 0

    def login(self, user, password):
        self.calls.append(("login", user, password))
        if not self._login_ok:
            raise mail.imaplib.IMAP4.error(f"AUTHENTICATIONFAILED login failed for {password}")
        return "OK", [b"success"]

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        self.calls.append(("search", charset, *criteria))
        return "OK", [b" ".join(self._search_result)]

    def fetch(self, num, parts):
        self.calls.append(("fetch", num, parts))
        raw = self._fetch_map.get(num, RECRUITER_RAW)
        return "OK", [(b"1 (BODY[] {%d}" % len(raw), raw), b")"]

    def logout(self):
        self.calls.append(("logout",))


# --- connect() ---------------------------------------------------------


def test_connect_uses_env_defaults(monkeypatch):
    monkeypatch.setenv("MERIT_IMAP_USER", "someone@example.invalid")
    monkeypatch.setenv("MERIT_IMAP_PASSWORD", "hunter2-secret")
    monkeypatch.delenv("MERIT_IMAP_HOST", raising=False)
    monkeypatch.delenv("MERIT_IMAP_MAILBOX", raising=False)

    fake = _FakeConn()
    captured = {}

    def fake_ssl(host):
        captured["host"] = host
        return fake

    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", fake_ssl)
    conn = mail.connect()

    assert captured["host"] == mail.DEFAULT_HOST
    assert conn is fake
    assert ("login", "someone@example.invalid", "hunter2-secret") in fake.calls
    assert ("select", mail.DEFAULT_MAILBOX, True) in fake.calls


def test_connect_missing_password_names_the_variable(monkeypatch):
    monkeypatch.setenv("MERIT_IMAP_USER", "someone@example.invalid")
    monkeypatch.delenv("MERIT_IMAP_PASSWORD", raising=False)

    with pytest.raises(mail.MailError, match="MERIT_IMAP_PASSWORD"):
        mail.connect()


def test_connect_missing_user_names_the_variable(monkeypatch):
    monkeypatch.delenv("MERIT_IMAP_USER", raising=False)
    monkeypatch.setenv("MERIT_IMAP_PASSWORD", "hunter2-secret")

    with pytest.raises(mail.MailError, match="MERIT_IMAP_USER"):
        mail.connect()


def test_connect_login_failure_never_leaks_password(monkeypatch, capsys):
    monkeypatch.setenv("MERIT_IMAP_USER", "someone@example.invalid")
    monkeypatch.setenv("MERIT_IMAP_PASSWORD", "hunter2-secret")

    fake = _FakeConn(login_ok=False)
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: fake)

    with pytest.raises(mail.MailError) as excinfo:
        mail.connect()

    assert "hunter2-secret" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    captured = capsys.readouterr()
    assert "hunter2-secret" not in captured.out
    assert "hunter2-secret" not in captured.err


def test_connect_never_touches_imaplib_debug(monkeypatch):
    monkeypatch.setenv("MERIT_IMAP_USER", "someone@example.invalid")
    monkeypatch.setenv("MERIT_IMAP_PASSWORD", "hunter2-secret")
    fake = _FakeConn()
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: fake)
    monkeypatch.setattr(mail.imaplib, "Debug", 0)

    mail.connect()

    assert mail.imaplib.Debug == 0
    assert fake.debug == 0


def test_connect_selects_readonly(monkeypatch):
    monkeypatch.setenv("MERIT_IMAP_USER", "someone@example.invalid")
    monkeypatch.setenv("MERIT_IMAP_PASSWORD", "hunter2-secret")
    monkeypatch.setenv("MERIT_IMAP_MAILBOX", "custom-box")
    fake = _FakeConn()
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: fake)

    mail.connect()

    assert ("select", "custom-box", True) in fake.calls


def test_connect_quotes_mailbox_name_containing_a_space(monkeypatch):
    monkeypatch.setenv("MERIT_IMAP_USER", "someone@example.invalid")
    monkeypatch.setenv("MERIT_IMAP_PASSWORD", "hunter2-secret")
    monkeypatch.setenv("MERIT_IMAP_MAILBOX", "Linkedin Jobs")
    fake = _FakeConn()
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: fake)

    mail.connect()

    assert ("select", '"Linkedin Jobs"', True) in fake.calls


# --- fetch_messages() ---------------------------------------------------


def test_fetch_messages_uses_peek_not_rfc822():
    fake = _FakeConn(search_result=(b"1",), fetch_map={b"1": RECRUITER_RAW})
    raws = mail.fetch_messages(fake)

    assert raws == [RECRUITER_RAW]
    fetch_calls = [c for c in fake.calls if c[0] == "fetch"]
    assert fetch_calls == [("fetch", b"1", "(BODY.PEEK[])")]
    assert "(RFC822)" not in [c[2] for c in fetch_calls]


def test_fetch_messages_issues_no_mutating_calls():
    fake = _FakeConn(
        search_result=(b"1", b"2"), fetch_map={b"1": RECRUITER_RAW, b"2": NEWSLETTER_RAW}
    )
    mail.fetch_messages(fake)

    mutating = {"store", "copy", "expunge", "delete", "uid", "append", "rename"}
    call_names = {c[0] for c in fake.calls}
    assert not (call_names & mutating)


# --- is_recruiter_message() ---------------------------------------------


def _parse(raw: bytes):
    return email.message_from_bytes(raw, policy=email.policy.default)


def test_recruiter_fixture_is_recognized():
    assert mail.is_recruiter_message(_parse(RECRUITER_RAW)) is True


def _real_inmail_raw() -> bytes:
    # Real-world shape (operational validation 2026-07-29): LinkedIn InMail
    # notifications arrive from inmail-hit-reply@linkedin.com with the
    # opportunity title as subject - no "sent you a message" marker.
    return (
        b"From: Ana Recruiter via LinkedIn <inmail-hit-reply@linkedin.com>\r\n"
        b"Subject: Remote Back-end Engineer Opportunity | Kotlin/JVM\r\n"
        b"Date: Tue, 28 Jul 2026 09:14:00 +0000\r\n"
        b"Message-ID: <inmail-0001@lva1-app.prod.linkedin.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Hi Sammy, I have a role that matches your background.\r\n"
    )


def test_real_inmail_sender_is_recognized_without_subject_marker():
    assert mail.is_recruiter_message(_parse(_real_inmail_raw())) is True


def test_inmail_sender_on_lookalike_domain_is_rejected():
    raw = _real_inmail_raw().replace(b"@linkedin.com", b"@evil-linkedin.com")
    assert mail.is_recruiter_message(_parse(raw)) is False


def test_newsletter_is_rejected():
    assert mail.is_recruiter_message(_parse(NEWSLETTER_RAW)) is False


def test_lookalike_domain_is_rejected():
    assert mail.is_recruiter_message(_parse(_lookalike_domain_raw())) is False


def test_job_alert_shaped_subject_is_rejected():
    assert mail.is_recruiter_message(_parse(_job_alert_raw())) is False


# --- message_text() ------------------------------------------------------


def test_plain_part_preferred_over_html():
    text = mail.message_text(_parse(RECRUITER_RAW))
    assert PLAIN_ONLY_SENTENCE in text
    assert SHARED_SENTENCE in text


def test_html_only_message_falls_back_with_no_tags_surviving():
    raw = (
        b"From: LinkedIn <messages-noreply@linkedin.com>\r\n"
        b"Subject: Sam sent you a message\r\n"
        b"Date: Tue, 28 Jul 2026 09:14:00 +0000\r\n"
        b"Message-ID: <html-only-0001@mail.linkedin.com>\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<html><body><p>We are <b>hiring</b> now.</p></body></html>\r\n"
    )
    text = mail.message_text(_parse(raw))
    assert text is not None
    assert "<" not in text and ">" not in text
    assert "hiring" in text


# --- slug() ---------------------------------------------------------------


def test_slug_normalizes_and_truncates():
    assert mail.slug("Alex Rivera sent you a message!!") == "alex-rivera-sent-you-a-message"


def test_slug_truncates_to_max_and_strips_trailing_dash():
    long_subject = "word " * 30
    result = mail.slug(long_subject)
    assert len(result) <= mail.SLUG_MAX
    assert not result.endswith("-")


def test_slug_empty_falls_back_to_message():
    assert mail.slug("!!!") == "message"


# --- ingest_messages(): recruiter happy path ------------------------------


def test_ingest_recruiter_message_writes_one_file(tmp_path):
    ingested, skipped = mail.ingest_messages([RECRUITER_RAW], tmp_path)

    assert len(ingested) == 1
    assert skipped == []
    body = ingested[0].path.read_text(encoding="utf-8")
    assert PLAIN_ONLY_SENTENCE in body
    assert "from: LinkedIn <messages-noreply@linkedin.com>" in body
    assert "subject: Alex Rivera sent you a message" in body
    assert "date: Tue, 28 Jul 2026 09:14:00 +0000" in body
    assert "message-id: <recruiter-0001@mail.linkedin.com>" in body


def test_ingest_recruiter_filename_shape(tmp_path):
    ingested, _ = mail.ingest_messages([RECRUITER_RAW], tmp_path)
    name = ingested[0].path.name
    digest8 = hashlib.sha256(b"<recruiter-0001@mail.linkedin.com>").hexdigest()[:8]
    assert name == f"2026-07-28-alex-rivera-sent-you-a-message-{digest8}.md"


def test_ingest_undated_message_uses_undated_literal(tmp_path):
    ingested, _ = mail.ingest_messages([_no_date_raw()], tmp_path)
    assert len(ingested) == 1
    assert ingested[0].path.name.startswith("undated-")


def test_ingest_newsletter_is_fully_skipped_without_body_leak(tmp_path):
    ingested, skipped = mail.ingest_messages([NEWSLETTER_RAW], tmp_path)

    assert ingested == []
    assert len(skipped) == 1
    assert "newsletter-0001" in skipped[0] or "weekly digest" in skipped[0].lower()
    assert "Unsubscribe at any time" not in skipped[0]


def test_ingest_written_file_not_world_readable(tmp_path):
    ingested, _ = mail.ingest_messages([RECRUITER_RAW], tmp_path)
    mode = ingested[0].path.stat().st_mode
    assert mode & 0o077 == 0


def test_ingest_no_message_id_falls_back_to_sha256_key(tmp_path):
    raw = _no_message_id_raw()
    ingested, _ = mail.ingest_messages([raw], tmp_path)
    assert len(ingested) == 1
    key = ingested[0].key
    assert key.startswith("sha256:")
    assert key == "sha256:" + hashlib.sha256(raw).hexdigest()

    # Prove all four identity sources agree: Ingested.key, .seen file,
    # filename digest8 suffix, and the written posting file's own header.
    seen_lines = (tmp_path / ".seen").read_text().splitlines()
    assert seen_lines == [key]

    digest8 = hashlib.sha256(key.encode()).hexdigest()[:8]
    assert ingested[0].path.name.endswith(f"-{digest8}.md")

    written = ingested[0].path.read_text()
    header_line = next(line for line in written.splitlines() if line.startswith("message-id:"))
    assert header_line == f"message-id: {key}"


def test_ingest_dedupes_same_raw_message_twice(tmp_path):
    ingested, _skipped = mail.ingest_messages([RECRUITER_RAW, RECRUITER_RAW], tmp_path)

    assert len(ingested) == 1
    seen_file = tmp_path / ".seen"
    lines = seen_file.read_text().splitlines()
    assert len(lines) == 1


def test_ingest_second_independent_call_ingests_nothing_new(tmp_path):
    mail.ingest_messages([RECRUITER_RAW], tmp_path)
    ingested2, _ = mail.ingest_messages([RECRUITER_RAW], tmp_path)
    assert ingested2 == []


def test_truncating_seen_and_rerunning_produces_no_duplicate(tmp_path):
    mail.ingest_messages([RECRUITER_RAW], tmp_path)
    (tmp_path / ".seen").write_text("")
    mail.ingest_messages([RECRUITER_RAW], tmp_path)

    md_files = list(tmp_path.glob("*.md"))
    assert len(md_files) == 1


def test_ingest_one_bad_message_never_aborts_the_batch(tmp_path):
    ingested, _skipped = mail.ingest_messages([_bad_raw(), RECRUITER_RAW], tmp_path)

    assert len(ingested) == 1
    assert ingested[0].subject == "Alex Rivera sent you a message"


def test_ingest_message_parse_exception_is_skipped(tmp_path, monkeypatch):
    original_from_bytes = mail.email.message_from_bytes
    calls = {"n": 0}

    def flaky_from_bytes(raw, policy=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("boom")
        return original_from_bytes(raw, policy=policy)

    monkeypatch.setattr(mail.email, "message_from_bytes", flaky_from_bytes)
    ingested, skipped = mail.ingest_messages([RECRUITER_RAW, RECRUITER_RAW], tmp_path)

    assert len(skipped) == 1
    assert len(ingested) == 1


# --- is_job_alert() -------------------------------------------------------


def test_job_alert_digest_fixture_is_detected():
    assert mail.is_job_alert(_parse(JOB_ALERT_DIGEST_RAW)) is True


def test_job_alert_sender_on_lookalike_domain_is_rejected():
    raw = JOB_ALERT_DIGEST_RAW.replace(b"@linkedin.com", b"@evil-linkedin.com")
    assert mail.is_job_alert(_parse(raw)) is False


def test_alert_check_accepts_subject_shape_recruiter_check_rejects():
    msg = _parse(_job_alert_raw())
    assert mail.is_job_alert(msg) is True
    assert mail.is_recruiter_message(msg) is False


def test_recruiter_and_alert_checks_are_mutually_exclusive():
    assert mail.is_job_alert(_parse(RECRUITER_RAW)) is False
    assert mail.is_recruiter_message(_parse(JOB_ALERT_DIGEST_RAW)) is False


# --- message_html() --------------------------------------------------------


def test_message_html_returns_html_part_not_plain():
    html = mail.message_html(_parse(JOB_ALERT_DIGEST_RAW))
    assert html is not None
    assert "<a href" in html


def test_message_html_returns_none_for_plain_only():
    plain_only_raw = (
        b"From: LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>\r\n"
        b"Subject: 5 new jobs and more\r\n"
        b"Date: Tue, 28 Jul 2026 09:14:00 +0000\r\n"
        b"Message-ID: <plain-only-alert-0001@mail.linkedin.com>\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"No links here.\r\n"
    )
    assert mail.message_html(_parse(plain_only_raw)) is None


# --- message_date() ---------------------------------------------------------


def test_message_date_formats_and_falls_back_to_undated():
    assert mail.message_date(_parse(JOB_ALERT_DIGEST_RAW)) == "2026-07-29"
    assert mail.message_date(_parse(_no_date_raw())) == "undated"


# --- ingest_alerts() ---------------------------------------------------------


def test_ingest_alerts_skips_non_alert_messages(tmp_path):
    entries, skipped = mail.ingest_alerts([NEWSLETTER_RAW, RECRUITER_RAW], tmp_path / "queue.json")

    assert entries == []
    assert len(skipped) == 2
    assert not any("Unsubscribe at any time" in reason for reason in skipped)
    assert not any("distributed retrieval systems" in reason for reason in skipped)


def test_ingest_alerts_one_bad_raw_never_aborts_the_batch(tmp_path):
    entries, _skipped = mail.ingest_alerts([b"garbage not really an email", JOB_ALERT_DIGEST_RAW], tmp_path / "queue.json")

    assert len(entries) == 2
    assert entries[0].title == "Senior Backend Engineer, REST APIs"


def test_ingest_alerts_second_run_adds_nothing(tmp_path):
    queue_path = tmp_path / "queue.json"
    first, _ = mail.ingest_alerts([JOB_ALERT_DIGEST_RAW], queue_path)
    second, _ = mail.ingest_alerts([JOB_ALERT_DIGEST_RAW], queue_path)

    assert len(first) == 2
    assert second == []
    assert len(mail.queue.load_entries(queue_path)) == 2


def test_env_config_falls_back_to_keychain(monkeypatch):
    from merit import mail

    monkeypatch.delenv("MERIT_IMAP_USER", raising=False)
    monkeypatch.delenv("MERIT_IMAP_PASSWORD", raising=False)
    monkeypatch.setattr(
        mail, "_keychain",
        {"merit-imap-user": "user@example.com", "merit-imap-pass": "s3cret"}.get,
    )

    _host, user, password, _mailbox = mail._env_config()

    assert user == "user@example.com"
    assert password == "s3cret"  # noqa: S105 - test fixture value


def test_env_config_env_wins_over_keychain(monkeypatch):
    from merit import mail

    monkeypatch.setenv("MERIT_IMAP_USER", "env-user")
    monkeypatch.setenv("MERIT_IMAP_PASSWORD", "env-pass")
    monkeypatch.setattr(mail, "_keychain", lambda service: "keychain-value")

    _, user, password, _ = mail._env_config()

    assert user == "env-user"
    assert password == "env-pass"  # noqa: S105 - test fixture value


def test_env_config_still_fails_loud_without_any_source(monkeypatch):
    from merit import mail

    monkeypatch.delenv("MERIT_IMAP_USER", raising=False)
    monkeypatch.delenv("MERIT_IMAP_PASSWORD", raising=False)
    monkeypatch.setattr(mail, "_keychain", lambda service: None)

    with pytest.raises(mail.MailError):
        mail._env_config()


def test_cursor_name_is_mailbox_scoped():
    from merit.mail import cursor_name

    assert cursor_name("InMail") == ".last-uid-inmail"
    assert cursor_name("Linkedin Jobs") == ".last-uid-linkedin-jobs"


def test_thread_id_extracted_from_body():
    from merit.mail import thread_id

    body = "Reply here:\nhttps://www.linkedin.com/messaging/thread/2-AbC123==/\nBest,"
    assert thread_id(body) == "2-AbC123=="
    assert thread_id("no linkedin link at all") is None
