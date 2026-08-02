"""Dossie views for tracked applications."""
import contextlib
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request

from merit import track
from merit.cli import _db_path, _dossier_root
from merit.serve import rendering
from merit.serve.rendering import templates

router = APIRouter()


def _row(db_path: str, app_id: int):
    with contextlib.closing(track._conn(db_path)) as conn, conn:
        return conn.execute(track._SELECT_ROW_SQL, {"id": app_id}).fetchone()


def _all_rows(db_path: str):
    with contextlib.closing(track._conn(db_path)) as conn, conn:
        return conn.execute(track._SELECT_SQL, {"status": None}).fetchall()


def _context(db_path: str, app_id: int, row) -> dict:
    dossier_dir = row["dossier_dir"]
    has_dossier = bool(dossier_dir) and Path(dossier_dir).is_dir()
    jd_path = Path(dossier_dir) / "jd.md" if has_dossier else None
    jd_text = jd_path.read_text(encoding="utf-8", errors="replace") if jd_path and jd_path.is_file() else None
    entries = track.entries(db_path, app_id) if has_dossier else []
    return {
        "view": "dossie",
        "app_id": app_id,
        "row": row,
        "statuses": track.STATUSES,
        "jd_text": jd_text,
        "has_dossier": has_dossier,
        "thread_entries": [(s, b) for s, src, b in entries if src == "thread"],
        "notes_entries": [(s, b) for s, src, b in entries if src == "notes"],
    }


def _not_found(request: Request):
    context = {"view": "dossie", "app_id": None, "not_found": True}
    return templates.TemplateResponse(request, "dossie.html", context, status_code=404)


def _form(body: bytes) -> dict:
    # ponytail: parse the urlencoded body with stdlib instead of
    # request.form(), which needs python-multipart (not a project
    # dependency); htmx/tests only ever send urlencoded form data here.
    return dict(parse_qsl(body.decode(errors="replace")))


@router.get("/dossie")
async def dossie_index(request: Request):
    db_path = _db_path()
    context = {"view": "dossie", "app_id": None, "applications": _all_rows(db_path)}
    return rendering.page(request, "dossie.html", context)


@router.get("/dossie/{app_id}")
async def dossie(request: Request, app_id: int):
    db_path = _db_path()
    row = _row(db_path, app_id)
    if row is None:
        return _not_found(request)
    return rendering.page(request, "dossie.html", _context(db_path, app_id, row))


@router.post("/dossie/{app_id}/status")
async def dossie_status(request: Request, app_id: int):
    db_path = _db_path()
    fields = _form(await request.body())
    track.set_status(db_path, app_id, fields.get("status", ""))
    row = _row(db_path, app_id)
    return rendering.page(request, "dossie.html", _context(db_path, app_id, row))


@router.post("/dossie/{app_id}/log")
async def dossie_log(request: Request, app_id: int):
    db_path = _db_path()
    if _row(db_path, app_id) is None:
        return _not_found(request)

    fields = _form(await request.body())
    file, text = fields.get("file", ""), fields.get("text", "")
    try:
        track.log(db_path, app_id, text, file=file, dossier_root=_dossier_root())
    except track.TrackError:
        # ponytail: silent no-op on empty/invalid log post, no error UI needed yet.
        pass

    entries = [(s, b) for s, src, b in track.entries(db_path, app_id) if src == file]
    context = {"log_file": file, "log_entries": entries, "app_id": app_id, "has_dossier": True}
    return rendering.page(request, "_dossie_log.html", context)
