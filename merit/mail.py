# merit/mail.py
"""Mail ingestion: stdlib IMAP + email parsing. No new deps; the graph core never imports this."""
import contextlib
import email
import email.policy
import email.utils
import hashlib
import imaplib
import json
import os
import re
import subprocess
import sys
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
# hit-reply@ = thread replies (mailbox recon 2026-08-04: 61/400 recent).
RECRUITER_SENDERS = ("inmail-hit-reply@linkedin.com", "hit-reply@linkedin.com")
JOB_ALERT_SENDERS = ("jobalerts-noreply@linkedin.com",)
JOB_ALERT_SUBJECT_MARKERS = ("and more", "new jobs", "job alert")
SLUG_MAX = 60

_SLUG_RUN = re.compile(r"[^a-z0-9]+")


class MailError(RuntimeError):
    pass


class SelectError(MailError):
    """A mailbox SELECT failed or returned a malformed response."""


class SearchError(MailError):
    """A SEARCH (or UID SEARCH) failed or returned a malformed response."""


@dataclass(frozen=True)
class Ingested:
    path: Path
    subject: str
    key: str


def _ok(typ: str, data, what: str, exc: type[MailError] = MailError) -> None:
    """Raise `exc` naming `what` unless `typ` is "OK" and `data` is well-formed.
    IMAP command methods return a status string you must check yourself - they
    do not raise on a missing mailbox or a state error. A malformed `data`
    (None, [None], or []) is never a legitimate empty result - a real empty
    mailbox/search returns [b""], which this deliberately does NOT reject."""
    malformed = data is None or data in ([None], [])
    if typ != "OK" or malformed:
        raise exc(f"IMAP {what} failed (status={typ!r})")


def _close_quietly(conn) -> None:
    """Best-effort logout so a broken connection is never left open when we
    are already about to raise for the real failure. Any exception here would
    just mask that real failure, so it is swallowed."""
    with contextlib.suppress(Exception):
        conn.logout()


_THREAD_RE = re.compile(r"linkedin\.com/messaging/thread/([A-Za-z0-9=_-]+)")


def thread_id(text: str) -> str | None:
    """LinkedIn conversation id from a message body - stable per thread, the
    join key between incoming replies and tracked applications."""
    match = _THREAD_RE.search(text)
    return match.group(1) if match else None


def cursor_name(mailbox: str) -> str:
    """UID cursors are per-mailbox (UIDs only mean something inside one
    mailbox), so the cursor file carries the mailbox in its name."""
    slug = re.sub(r"[^a-z0-9]+", "-", mailbox.lower()).strip("-")
    return f".last-uid-{slug}"


def _keychain(service: str) -> str | None:
    """macOS keychain lookup so launchd jobs (and plain CLI runs) work with
    no credentials in env or files. Value never gets logged or echoed."""
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(  # noqa: S603 - fixed binary, fixed args
            ["/usr/bin/security", "find-generic-password", "-s", service, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _env_config() -> tuple[str, str, str, str]:
    host = os.environ.get("MERIT_IMAP_HOST", DEFAULT_HOST)
    user = os.environ.get("MERIT_IMAP_USER") or _keychain("merit-imap-user")
    password = os.environ.get("MERIT_IMAP_PASSWORD") or _keychain("merit-imap-pass")
    mailbox = os.environ.get("MERIT_IMAP_MAILBOX", DEFAULT_MAILBOX)
    if not user:
        raise MailError(
            "missing credentials: set MERIT_IMAP_USER or store keychain item merit-imap-user"
        )
    if not password:
        raise MailError(
            "missing credentials: set MERIT_IMAP_PASSWORD or store keychain item merit-imap-pass"
        )
    return host, user, password, mailbox


def connect() -> imaplib.IMAP4_SSL:
    host, user, password, mailbox = _env_config()

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
        _close_quietly(conn)
        raise MailError(f"IMAP login failed for user {user} on host {host}")
    # imaplib.IMAP4.select() does not quote its argument, so a mailbox name
    # containing a space (e.g. Gmail label "Linkedin Jobs") produces an
    # invalid multi-word SELECT on the wire. Quote only when needed so
    # existing unquoted single-word mailbox names keep behaving identically.
    select_mailbox = f'"{mailbox}"' if " " in mailbox else mailbox
    typ, data = conn.select(select_mailbox, readonly=True)
    try:
        _ok(typ, data, f"select mailbox {mailbox!r}", SelectError)
    except SelectError:
        _close_quietly(conn)
        raise
    return conn


def _read_cursor(path: Path) -> dict | None:
    """Return the parsed cursor record, or None on anything short of a clean
    read (missing file, corrupt JSON, not an object) - any of those means
    "no usable cursor", never a crash."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _write_cursor(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(record), encoding="utf-8")
    tmp_path.chmod(0o600)
    tmp_path.replace(path)


def _fetch_messages_cursor(conn) -> list[bytes]:
    cursor_path: Path = conn.merit_cursor_path
    host, user, _password, mailbox = _env_config()

    # response() pops the buffered UIDVALIDITY value set by the preceding
    # SELECT - it must be read here, before any other command, or it is gone.
    _typ, uidvalidity_data = conn.response("UIDVALIDITY")
    uidvalidity = (
        uidvalidity_data[0].decode() if uidvalidity_data and uidvalidity_data[0] else ""
    )
    identity = {"host": host, "user": user, "mailbox": mailbox, "uidvalidity": uidvalidity}

    cursor = _read_cursor(cursor_path)
    # A stale cursor (identity mismatch, or none on disk) must never be read
    # as "skip everything" - fall back to a full scan instead.
    identity_matches = cursor is not None and all(cursor.get(k) == v for k, v in identity.items())
    last_uid = cursor.get("uid") if identity_matches else None

    if last_uid is None:
        typ, data = conn.uid("SEARCH", "ALL")
    else:
        typ, data = conn.uid("SEARCH", "UID", f"{last_uid + 1}:*")
    _ok(typ, data, "UID SEARCH", SearchError)
    raw_uids = [int(u) for u in data[0].split()] if data[0] else []
    # IMAP's "n:*" range returns the highest-UID message even when n exceeds
    # every UID present, so the server-side search alone is not enough - the
    # client must filter to strictly-newer UIDs itself.
    new_uids = [u for u in raw_uids if u > last_uid] if last_uid is not None else raw_uids

    raws: list[bytes] = []
    for uid in new_uids:
        typ, msg_data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
        _ok(typ, msg_data, f"UID FETCH {uid}")
        for part in msg_data:
            if isinstance(part, tuple):
                raws.append(part[1])

    # Cursor only ever advances: a transient empty/lower search result must
    # not regress what is already on disk in the same run.
    candidates = raw_uids + ([last_uid] if last_uid is not None else [])
    new_last_uid = max(candidates) if candidates else 0
    _write_cursor(cursor_path, {**identity, "uid": new_last_uid})
    return raws


def fetch_messages(conn) -> list[bytes]:
    if getattr(conn, "merit_cursor", None):
        return _fetch_messages_cursor(conn)
    typ, data = conn.search(None, "ALL")
    _ok(typ, data, "search ALL", SearchError)
    nums = data[0].split() if data[0] else []
    raws: list[bytes] = []
    for num in nums:
        typ, msg_data = conn.fetch(num, "(BODY.PEEK[])")
        _ok(typ, msg_data, f"fetch message {num!r}")
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


@dataclass(frozen=True)
class ConversationEvent:
    key: str
    thread: str
    subject: str
    date: str
    body: str


def _read_seen(out_dir: Path) -> set[str]:
    seen_path = Path(out_dir) / ".seen"
    if not seen_path.exists():
        return set()
    return {line.strip() for line in seen_path.read_text().splitlines() if line.strip()}


def mark_seen(out_dir: Path, key: str) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / ".seen").open("a", encoding="utf-8") as fh:
        fh.write(key + "\n")


def match_conversations(
    raws: Iterable[bytes], thread_ids: set[str], out_dir: Path
) -> tuple[list[ConversationEvent], list[bytes]]:
    """Split raws into (conversation events, remaining). A conversation event
    is a recruiter message whose body carries a thread id that is already
    tracked - it belongs in the application's dossier, never in the vagas
    list. Already-seen events are dropped (dedup shared with .seen)."""
    events: list[ConversationEvent] = []
    remaining: list[bytes] = []
    seen = _read_seen(out_dir)
    for raw in raws:
        try:
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            if is_recruiter_message(msg):
                text = message_text(msg)
                tid = thread_id(text or "")
                if tid and tid in thread_ids:
                    key = message_key(msg, raw)
                    if key not in seen:
                        events.append(
                            ConversationEvent(
                                key=key,
                                thread=tid,
                                subject=str(msg["Subject"] or ""),
                                date=str(msg["Date"] or ""),
                                body=text or "",
                            )
                        )
                    continue
        except Exception:  # noqa: S110 - malformed mail falls through to ingest's reporting
            pass
        remaining.append(raw)
    return events, remaining


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
