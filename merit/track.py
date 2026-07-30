"""Application ledger: schema, validation, SQL, and markdown rendering. stdlib only."""
import contextlib
import sqlite3
from datetime import UTC, datetime

STATUSES = ("found", "queued", "applied", "screening", "interview", "offer", "rejected", "withdrawn")

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
        updated_at TEXT NOT NULL
    )
"""

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


def _conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE_SQL)
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
        return cur.lastrowid


def set_status(db_path: str, app_id: int, status: str, *, note: str | None = None) -> None:
    _validate(status)
    now = datetime.now(UTC).isoformat()
    with contextlib.closing(_conn(db_path)) as conn, conn:
        cur = conn.execute(_UPDATE_SQL, {"status": status, "note": note, "now": now, "id": app_id})
        if cur.rowcount == 0:
            raise TrackError(f"no application with id {app_id}")


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
