"""Fila view.

Preventive filters (owner-approved 2026-08-03, same grammar as rank): stale
(30+ days), on-site-in-title and frias (score <= 0) leave the default list -
counted in the header, revealed with ?hidden=1. Alerts carry no body, so the
score and the workplace signal come from the title alone.
"""
import os
from dataclasses import asdict
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Request

from merit import profile, queue, rank, track
from merit.serve import rendering

router = APIRouter()

# Integration-wave cap (live smoke 2026-08-01: 3274 hot rows rendered at once).
FILA_LIMIT = 50
STALE_DAYS = 30


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


def _reason(entry: queue.Entry, score: int, tracked_id: int | None) -> str | None:
    if tracked_id is not None:
        return "acompanhando"
    # Digests fold location into the company string ("Acme - SP (On-site)"),
    # so the workplace signal lives in title + company.
    if rank.classify_workplace(f"{entry.title} {entry.company or ''}") == "onsite":
        return "on-site"
    if score <= 0:
        return "fria"
    return None


def _rows(show_hidden: bool) -> dict:
    # Owner call 2026-08-03: stale entries are gone entirely - not listed,
    # not counted, not behind the reveal toggle.
    entries = [
        entry
        for entry in queue.load_entries(_queue_path())
        if not queue.is_stale(entry, days=STALE_DAYS)
    ]
    profile_path = _profile_path()
    prof = profile.load_profile(profile_path) if Path(profile_path).is_file() else None
    tracked = track.sources(_db_path())

    annotated = []
    counts = {"onsite": 0, "cold": 0, "tracked": 0}
    for entry in entries:
        score = rank.score_text(prof, entry.title)[3] if prof else 0
        app_id = tracked.get(entry.url)
        reason = _reason(entry, score, app_id)
        if reason == "on-site":
            counts["onsite"] += 1
        elif reason == "fria":
            counts["cold"] += 1
        elif reason == "acompanhando":
            counts["tracked"] += 1
        annotated.append({**asdict(entry), "score": score, "reason": reason, "app_id": app_id})

    annotated.sort(key=lambda e: e["score"], reverse=True)
    visible = [e for e in annotated if e["reason"] is None]
    displayed = annotated if show_hidden else visible
    return {
        "rows": displayed[:FILA_LIMIT],
        "more": max(0, len(displayed) - FILA_LIMIT),
        "total": len(annotated),
        "visible_n": len(visible),
        "counts": counts,
        "show_hidden": show_hidden,
    }


@router.get("/fila")
async def fila(request: Request):
    return rendering.page(
        request,
        "fila.html",
        {"view": "fila", **_rows(request.query_params.get("hidden") == "1")},
    )


@router.post("/fila/discard")
async def discard(request: Request):
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    url = form["url"][0]
    queue.discard(_queue_path(), url)
    return rendering.templates.TemplateResponse(request, "_fila_rows.html", _rows(show_hidden=False))


@router.post("/fila/track")
async def track_entry(
    request: Request,
):
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    url = form["url"][0]
    title = form["title"][0]
    company = form["company"][0]
    track.add(
        _db_path(),
        url,
        title=title,
        company=company or None,
        status="queued",
        dossier_root=_dossier_root(),
    )
    # Batch triage: stay in the list; the dossier is one click away via the badge.
    return rendering.templates.TemplateResponse(request, "_fila_rows.html", _rows(show_hidden=False))
