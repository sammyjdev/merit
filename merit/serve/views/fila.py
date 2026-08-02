"""Fila view."""
import os
from dataclasses import asdict
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response

from merit import profile, queue, track
from merit.serve import rendering

router = APIRouter()


def _queue_path() -> Path:
    return Path(os.environ.get("MERIT_QUEUE_PATH", str(queue.QUEUE_PATH)))


def _db_path() -> str:
    path = Path(os.environ.get("MERIT_DB", Path.home() / ".merit" / "merit.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _dossier_root() -> Path:
    return Path(_db_path()).parent / "applications"


def _profile_path() -> str:
    return os.environ.get("MERIT_PROFILE", "profile/profile.yaml")


def _rows(show_cold: bool) -> dict:
    entries = queue.load_entries(_queue_path())
    profile_path = _profile_path()
    terms = profile.strong_terms(profile.load_profile(profile_path)) if Path(profile_path).is_file() else []
    hot_entries = [entry for entry in entries if queue.is_hot(entry.title, terms)]
    cold = [entry for entry in entries if not queue.is_hot(entry.title, terms)]
    hot = [
        {**asdict(entry), "score": sum(term in entry.title.lower() for term in set(terms))}
        for entry in hot_entries
    ]
    hot.sort(key=lambda entry: entry["score"], reverse=True)
    return {"hot": hot, "cold": cold, "show_cold": show_cold}


@router.get("/fila")
async def fila(request: Request):
    return rendering.page(
        request,
        "fila.html",
        {"view": "fila", **_rows(request.query_params.get("all") == "1")},
    )


@router.post("/fila/discard")
async def discard(request: Request):
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    url = form["url"][0]
    queue.discard(_queue_path(), url)
    return rendering.templates.TemplateResponse(request, "_fila_rows.html", _rows(show_cold=False))


@router.post("/fila/track")
async def track_entry(
    request: Request,
):
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    url = form["url"][0]
    title = form["title"][0]
    company = form["company"][0]
    app_id = track.add(
        _db_path(),
        url,
        title=title,
        company=company or None,
        status="queued",
        dossier_root=_dossier_root(),
    )
    return Response(status_code=200, headers={"HX-Redirect": f"/dossie/{app_id}"})
