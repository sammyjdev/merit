"""Rank view: live deterministic scoring of the InMail inbox (spec 2026-08-03)."""
import os
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, Response

from merit import profile, rank, track
from merit.serve import rendering

router = APIRouter()

# Same lesson as fila's FILA_LIMIT (live smoke 2026-08-01).
RANK_LIMIT = 50


def _inbox_dir() -> Path:
    return Path(os.environ.get("MERIT_INBOX", "corpus/inbox"))


def _db_path() -> str:
    path = Path(os.environ.get("MERIT_DB", Path.home() / ".merit" / "merit.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _dossier_root() -> Path:
    return Path(_db_path()).parent / "applications"


def _profile_path() -> str:
    return os.environ.get("MERIT_PROFILE", "profile/profile.yaml")


def _posting_path(name: str) -> Path:
    """Resolve a plain .md filename inside the inbox; anything else is 404."""
    if Path(name).name != name or not name.endswith(".md"):
        raise HTTPException(status_code=404)
    path = _inbox_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return path


@router.get("/rank")
async def rank_page(request: Request):
    prof = profile.load_profile(_profile_path())
    rows, skipped = rank.rank_dir(prof, _inbox_dir())
    show_all = request.query_params.get("all") == "1"
    shown = rows if show_all else rows[:RANK_LIMIT]
    return rendering.page(
        request,
        "rank.html",
        {
            "view": "rank",
            "rows": shown,
            "total": len(rows),
            "more": 0 if show_all else max(0, len(rows) - RANK_LIMIT),
            "skipped": skipped,
        },
    )


@router.get("/rank/posting/{name}")
async def posting(request: Request, name: str):
    path = _posting_path(name)
    text = path.read_text(encoding="utf-8", errors="replace")
    prof = profile.load_profile(_profile_path())
    return rendering.templates.TemplateResponse(
        request, "_rank_detail.html", {"hits": rank.hit_names(prof, text), "body": text}
    )


@router.post("/rank/track")
async def track_posting(request: Request):
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    name = form["file"][0]
    title = form["title"][0]
    path = _posting_path(name)
    app_id = track.add(
        _db_path(),
        str(path),
        title=title,
        status="queued",
        dossier_root=_dossier_root(),
    )
    return Response(status_code=200, headers={"HX-Redirect": f"/dossie/{app_id}"})
