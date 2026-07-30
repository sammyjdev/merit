"""Application ledger: schema, validation, SQL, and markdown rendering. stdlib only."""
import contextlib
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

STATUSES = ("found", "queued", "applied", "screening", "interview", "offer", "rejected", "withdrawn")

LOG_FILES = ("thread", "notes")
DIR_MODE = 0o700
FILE_MODE = 0o600
SHOW_ENTRIES = 3
SLUG_MAX = 60

_SLUG_RUN = re.compile(r"[^a-z0-9]+")
_ENTRY_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00)$", re.MULTILINE)

_CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS applications (
        id         INTEGER PRIMARY KEY,
        source     TEXT NOT NULL,
        title      TEXT,
        company    TEXT,
        status     TEXT NOT NULL,
        note       TEXT,
        session_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        dossier_dir TEXT
    )
"""

_ADD_COLUMN_SQL = "ALTER TABLE applications ADD COLUMN dossier_dir TEXT"

_INSERT_SQL = """
    INSERT INTO applications
        (source, title, company, status, note, session_id, created_at, updated_at)
    VALUES
        (:source, :title, :company, :status, :note, :session_id, :created_at, :updated_at)
"""

_UPDATE_SQL = """
    UPDATE applications
    SET status = :status, note = COALESCE(:note, note), updated_at = :now
    WHERE id = :id
"""

_SELECT_SQL = """
    SELECT id, title, company, status, updated_at, note
    FROM applications
    WHERE (:status IS NULL OR status = :status)
    ORDER BY id
"""

_SELECT_ROW_SQL = "SELECT * FROM applications WHERE id = :id"
_SET_DOSSIER_SQL = "UPDATE applications SET dossier_dir = :dossier_dir WHERE id = :id"


class TrackError(RuntimeError):
    pass


def _validate(status: str) -> None:
    if status not in STATUSES:
        raise TrackError(f"invalid status {status!r}; valid: {', '.join(STATUSES)}")


def _cell(value: object) -> str:
    if value is None or value == "":
        return "-"
    text = str(value).replace("|", "\\|")
    return text.replace("\n", " ")


def _plain(value: object) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _slug(*candidates: str | None) -> str:
    for candidate in candidates:
        text = _SLUG_RUN.sub("-", (candidate or "").lower()).strip("-")[:SLUG_MAX].strip("-")
        if text:
            return text
    return "application"


def _write_private(path: Path, content: str) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.chmod(FILE_MODE)
    tmp_path.replace(path)


def _jd_content(source: str) -> str:
    candidate = Path(source)
    if candidate.suffix.lower() == ".md" and candidate.is_file():
        try:
            return candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return f"# jd\n\nsource: {source}\n"


def _dossier_path(
    root: str | Path, app_id: int, title: str | None, company: str | None, source: str
) -> Path:
    return Path(root) / f"{app_id}-{_slug(title, company, source)}"


def _ensure_dossier(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(DIR_MODE)
    path.mkdir(exist_ok=True)
    path.chmod(DIR_MODE)
    stubs = {"jd.md": _jd_content(source), "thread.md": "# thread\n", "notes.md": "# notes\n"}
    for name, content in stubs.items():
        stub = path / name
        if not stub.exists():
            _write_private(stub, content)
    return path


def _escape_boundaries(body: str) -> str:
    # A pasted line shaped exactly like an entry header would later be parsed
    # by _entries() as a boundary, fabricating a phantom entry. Escape it
    # markdown-style on write; the file stays human-readable.
    return "\n".join(
        "\\" + line if _ENTRY_RE.match(line) else line for line in body.splitlines()
    )


def _entries(text: str) -> list[tuple[str, str]]:
    matches = list(_ENTRY_RE.finditer(text))
    result = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        result.append((match.group(1), text[start:end].strip()))
    return result


def _conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE_SQL)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(applications)")}
    if "dossier_dir" not in columns:
        conn.execute(_ADD_COLUMN_SQL)
    return conn


def add(
    db_path: str,
    source: str,
    *,
    title: str | None = None,
    company: str | None = None,
    status: str = "found",
    note: str | None = None,
    session_id: str | None = None,
    dossier_root: str | Path | None = None,
) -> int:
    _validate(status)
    now = datetime.now(UTC).isoformat()
    with contextlib.closing(_conn(db_path)) as conn, conn:
        cur = conn.execute(
            _INSERT_SQL,
            {
                "source": source,
                "title": title,
                "company": company,
                "status": status,
                "note": note,
                "session_id": session_id,
                "created_at": now,
                "updated_at": now,
            },
        )
        app_id = cur.lastrowid
        if dossier_root is not None:
            path = _ensure_dossier(_dossier_path(dossier_root, app_id, title, company, source), source)
            conn.execute(_SET_DOSSIER_SQL, {"dossier_dir": str(path), "id": app_id})
        return app_id


def set_status(db_path: str, app_id: int, status: str, *, note: str | None = None) -> None:
    _validate(status)
    now = datetime.now(UTC).isoformat()
    with contextlib.closing(_conn(db_path)) as conn, conn:
        cur = conn.execute(_UPDATE_SQL, {"status": status, "note": note, "now": now, "id": app_id})
        if cur.rowcount == 0:
            raise TrackError(f"no application with id {app_id}")


def log(
    db_path: str,
    app_id: int,
    text: str,
    *,
    file: str = "thread",
    dossier_root: str | Path | None = None,
) -> Path:
    if file not in LOG_FILES:
        raise TrackError(f"invalid file {file!r}; valid: {', '.join(LOG_FILES)}")
    body = text.strip()
    if not body:
        raise TrackError("empty log entry")
    stamp = datetime.now(UTC).isoformat()
    with contextlib.closing(_conn(db_path)) as conn, conn:
        row = conn.execute(_SELECT_ROW_SQL, {"id": app_id}).fetchone()
        if row is None:
            raise TrackError(f"no application with id {app_id}")
        dossier = row["dossier_dir"]
        if not dossier:
            if dossier_root is None:
                raise TrackError(f"application {app_id} has no dossier; re-add with --dir")
            dossier = str(_dossier_path(dossier_root, app_id, row["title"], row["company"], row["source"]))
            conn.execute(_SET_DOSSIER_SQL, {"dossier_dir": dossier, "id": app_id})
        path = _ensure_dossier(Path(dossier), row["source"]) / f"{file}.md"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n## {stamp}\n\n{_escape_boundaries(body)}\n")
        path.chmod(FILE_MODE)
    return path


def show_markdown(db_path: str, app_id: int) -> str:
    with contextlib.closing(_conn(db_path)) as conn, conn:
        row = conn.execute(_SELECT_ROW_SQL, {"id": app_id}).fetchone()
    if row is None:
        raise TrackError(f"no application with id {app_id}")

    dossier_dir = row["dossier_dir"]
    dossier = Path(dossier_dir) if dossier_dir else None
    has_dossier = dossier is not None and dossier.is_dir()

    files = "-"
    combined: list[tuple[str, str, str]] = []
    if has_dossier:
        files = ", ".join(sorted(p.name for p in dossier.iterdir() if p.is_file())) or "-"
        for source in LOG_FILES:
            log_path = dossier / f"{source}.md"
            if log_path.is_file():
                text = log_path.read_text(encoding="utf-8", errors="replace")
                combined.extend((stamp, source, body) for stamp, body in _entries(text))

    entries = sorted(combined)[-SHOW_ENTRIES:]

    lines = [
        f"id: {row['id']}",
        f"title: {_plain(row['title'])}",
        f"company: {_plain(row['company'])}",
        f"status: {_plain(row['status'])}",
        f"source: {_plain(row['source'])}",
        f"session_id: {_plain(row['session_id'])}",
        f"created_at: {_plain(row['created_at'])}",
        f"updated_at: {_plain(row['updated_at'])}",
        f"note: {_plain(row['note'])}",
        "",
        f"dossier: {_plain(dossier_dir)}",
        f"files: {files}",
        "",
        f"last {SHOW_ENTRIES} log entries:",
        "",
    ]
    if entries:
        for entry_stamp, source, body in entries:
            lines.append(f"## {entry_stamp} ({source})")
            lines.append("")
            lines.append(body)
            lines.append("")
        lines.pop()
    else:
        lines.append("none")
    return "\n".join(lines)


def list_markdown(db_path: str, status: str | None = None) -> str:
    if status is not None:
        _validate(status)
    with contextlib.closing(_conn(db_path)) as conn, conn:
        rows = conn.execute(_SELECT_SQL, {"status": status}).fetchall()
    if not rows:
        return "no applications"
    lines = [
        "| id | title | company | status | updated_at | note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['id']} | {_cell(row['title'])} | {_cell(row['company'])} | "
            f"{_cell(row['status'])} | {_cell(row['updated_at'])} | {_cell(row['note'])} |"
        )
    return "\n".join(lines)
