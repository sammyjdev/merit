# merit/mail.py
"""Mail ingestion: stdlib IMAP + email parsing. No new deps; the graph core never imports this."""
import email
import email.policy
import email.utils
import hashlib
import imaplib
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from merit import queue
from merit.fetch import html_to_text

DEFAULT_HOST = "imap.gmail.com"
DEFAULT_MAILBOX = "merit"
INBOX_DIR = Path("corpus/inbox")
RECRUITER_DOMAIN = "linkedin.com"
RECRUITER_SUBJECT_MARKERS = ("sent you a message", "new message from", "inmail")
# Real InMail notifications carry the opportunity title as subject (no marker);
# their sender is stable (operational validation 2026-07-29, 218/218 messages).
RECRUITER_SENDERS = ("inmail-hit-reply@linkedin.com",)
JOB_ALERT_SENDERS = ("jobalerts-noreply@linkedin.com",)
JOB_ALERT_SUBJECT_MARKERS = ("and more", "new jobs", "job alert")
SLUG_MAX = 60

_SLUG_RUN = re.compile(r"[^a-z0-9]+")


class MailError(RuntimeError):
    pass


@dataclass(frozen=True)
class Ingested:
    path: Path
    subject: str
    key: str


def connect() -> imaplib.IMAP4_SSL:
    host = os.environ.get("MERIT_IMAP_HOST", DEFAULT_HOST)
    user = os.environ.get("MERIT_IMAP_USER")
    password = os.environ.get("MERIT_IMAP_PASSWORD")
    mailbox = os.environ.get("MERIT_IMAP_MAILBOX", DEFAULT_MAILBOX)
    if not user:
        raise MailError("missing required env var MERIT_IMAP_USER")
    if not password:
        raise MailError("missing required env var MERIT_IMAP_PASSWORD")

    conn = imaplib.IMAP4_SSL(host)
    login_failed = False
    try:
        conn.login(user, password)
    except imaplib.IMAP4.error:
        login_failed = True
    if login_failed:
        # imaplib error text can embed the attempted command, which may itself
        # echo credentials back - never chain the original exception. Raising
        # here, outside the except block, means no exception is currently
        # being handled, so __context__ is None on the raised MailError (not
        # merely suppressed for display, which `raise ... from None` inside
        # the except block would leave it as).
        raise MailError(f"IMAP login failed for user {user} on host {host}")
    # imaplib.IMAP4.select() does not quote its argument, so a mailbox name
    # containing a space (e.g. Gmail label "Linkedin Jobs") produces an
    # invalid multi-word SELECT on the wire. Quote only when needed so
    # existing unquoted single-word mailbox names keep behaving identically.
    select_mailbox = f'"{mailbox}"' if " " in mailbox else mailbox
    conn.select(select_mailbox, readonly=True)
    return conn


def fetch_messages(conn) -> list[bytes]:
    _typ, data = conn.search(None, "ALL")
    nums = data[0].split() if data and data[0] else []
    raws: list[bytes] = []
    for num in nums:
        _typ, msg_data = conn.fetch(num, "(BODY.PEEK[])")
        for part in msg_data:
            if isinstance(part, tuple):
                raws.append(part[1])
    return raws


def _sender_domain(msg) -> str:
    addr = email.utils.parseaddr(str(msg["From"]))[1]
    return addr.rsplit("@", 1)[-1].lower()


def is_recruiter_message(msg) -> bool:
    addr = email.utils.parseaddr(str(msg["From"]))[1].lower()
    if addr in RECRUITER_SENDERS:
        return True
    domain = _sender_domain(msg)
    domain_ok = domain == RECRUITER_DOMAIN or domain.endswith("." + RECRUITER_DOMAIN)
    subject = str(msg["Subject"] or "").lower()
    subject_ok = any(marker in subject for marker in RECRUITER_SUBJECT_MARKERS)
    return domain_ok and subject_ok


def is_job_alert(msg) -> bool:
    addr = email.utils.parseaddr(str(msg["From"]))[1].lower()
    if addr in JOB_ALERT_SENDERS:
        return True
    domain = _sender_domain(msg)
    domain_ok = domain == RECRUITER_DOMAIN or domain.endswith("." + RECRUITER_DOMAIN)
    subject = str(msg["Subject"] or "").lower()
    subject_ok = any(marker in subject for marker in JOB_ALERT_SUBJECT_MARKERS)
    return domain_ok and subject_ok


def message_text(msg) -> str | None:
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is None:
        return None
    content = body.get_content()
    if body.get_content_type() == "text/html":
        return html_to_text(content)
    return content


def message_html(msg) -> str | None:
    body = msg.get_body(preferencelist=("html",))
    if body is None:
        return None
    return body.get_content()


def message_date(msg) -> str:
    try:
        return email.utils.parsedate_to_datetime(msg["Date"]).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return "undated"


def message_key(msg, raw: bytes) -> str:
    message_id = str(msg["Message-ID"] or "").strip()
    if message_id:
        return message_id
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def slug(subject: str) -> str:
    lowered = _SLUG_RUN.sub("-", subject.lower()).strip("-")
    truncated = lowered[:SLUG_MAX].strip("-")
    return truncated or "message"


def posting_path(msg, raw: bytes, out_dir: Path) -> Path:
    date = message_date(msg)
    key = message_key(msg, raw)
    digest8 = hashlib.sha256(key.encode()).hexdigest()[:8]
    subject = str(msg["Subject"] or "")
    filename = f"{date}-{slug(subject)}-{digest8}.md"
    return out_dir / filename


def render(msg, text: str, key: str) -> str:
    """Render the posting file. `key` must be the same identity computed by
    `message_key(msg, raw)` for this message - the written `message-id:` header
    has to match what `.seen`/`Ingested.key`/the filename digest use, or a
    `.seen` rebuild from posting files would derive different keys and
    re-ingest forever."""
    return (
        "---\n"
        f"from: {msg['From']}\n"
        f"subject: {msg['Subject']}\n"
        f"date: {msg['Date']}\n"
        f"message-id: {key}\n"
        "---\n\n"
        f"{text}\n"
    )


def ingest_messages(raws: Iterable[bytes], out_dir: Path) -> tuple[list[Ingested], list[str]]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    seen_path = out_dir / ".seen"
    seen: set[str] = set()
    if seen_path.exists():
        seen = {line.strip() for line in seen_path.read_text().splitlines() if line.strip()}

    ingested: list[Ingested] = []
    skipped: list[str] = []

    for raw in raws:
        try:
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            key = message_key(msg, raw)
            if key in seen:
                continue
            subject = str(msg["Subject"] or "")
            if not is_recruiter_message(msg):
                skipped.append(f"skipped (not a recruiter message): subject={subject!r} key={key}")
                continue
            text = message_text(msg)
            if text is None:
                skipped.append(f"skipped (no text body): subject={subject!r} key={key}")
                continue
            path = posting_path(msg, raw, out_dir)
            tmp_path = path.with_name(path.name + ".tmp")
            tmp_path.write_text(render(msg, text, key), encoding="utf-8")
            tmp_path.chmod(0o600)
            tmp_path.replace(path)

            with seen_path.open("a", encoding="utf-8") as fh:
                fh.write(key + "\n")

            seen.add(key)
            ingested.append(Ingested(path=path, subject=subject, key=key))
        except Exception as exc:
            # Intentional catch-all: one malformed/exception-raising message must
            # never abort the batch (per issue acceptance). exc is the stdlib
            # exception str only - never message body/secrets - so it is safe to
            # surface in the skip reason.
            skipped.append(f"skipped (error: {exc}): unparseable message")
            continue

    return ingested, skipped


def ingest_alerts(raws: Iterable[bytes], queue_path: Path) -> tuple[list[queue.Entry], list[str]]:
    all_entries: list[queue.Entry] = []
    skipped: list[str] = []

    for raw in raws:
        try:
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            subject = str(msg["Subject"] or "")
            if not is_job_alert(msg):
                skipped.append(f"skipped (not a job alert): subject={subject!r}")
                continue
            html = message_html(msg)
            if html is None:
                skipped.append(f"skipped (no html body): subject={subject!r}")
                continue
            all_entries.extend(queue.parse_alert(html, message_date(msg)))
        except Exception as exc:
            # Same batch-isolation contract as ingest_messages: one bad raw
            # must never abort the batch. exc is the stdlib exception str
            # only - never message body/secrets.
            skipped.append(f"skipped (error: {exc}): unparseable message")
            continue

    added = queue.append_entries(all_entries, queue_path)
    return added, skipped
