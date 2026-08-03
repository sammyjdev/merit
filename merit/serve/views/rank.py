"""Rank view: live deterministic scoring of the InMail inbox (spec 2026-08-03).

Preventive filters (owner-approved 2026-08-03): tracked, on-site, stale (30+
days) and weak (score <= 0) postings leave the default list - never silently,
always counted in the header with a reveal toggle.
"""
import os
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request

from merit import goldenset, profile, rank, track
from merit.serve import rendering

router = APIRouter()

# Same lesson as fila's FILA_LIMIT (live smoke 2026-08-01).
RANK_LIMIT = 50
STALE_DAYS = 30


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


def _reason(row: rank.Row, tracked_id: int | None) -> str | None:
    if tracked_id is not None:
        return "acompanhando"
    if row.workplace == "onsite":
        return "on-site"
    if row.score <= 0:
        return "fraca"
    return None


def _rows(show_hidden: bool, show_all: bool) -> dict:
    prof = profile.load_profile(_profile_path())
    all_rows, skipped = rank.rank_dir(prof, _inbox_dir())
    # Owner call 2026-08-03: stale postings are gone entirely - not listed,
    # not counted, not behind the reveal toggle.
    rows = [r for r in all_rows if r.age_days is None or r.age_days <= STALE_DAYS]
    tracked = track.sources(_db_path())
    inbox = _inbox_dir()

    annotated = []
    counts = {"onsite": 0, "weak": 0, "tracked": 0}
    for row in rows:
        app_id = tracked.get(str(inbox / row.file))
        reason = _reason(row, app_id)
        if reason == "acompanhando":
            counts["tracked"] += 1
        elif reason == "on-site":
            counts["onsite"] += 1
        elif reason == "fraca":
            counts["weak"] += 1
        annotated.append({**row._asdict(), "reason": reason, "app_id": app_id})

    visible = [entry for entry in annotated if entry["reason"] is None]
    displayed = annotated if show_hidden else visible
    more = 0 if show_all else max(0, len(displayed) - RANK_LIMIT)
    return {
        "rows": displayed if show_all else displayed[:RANK_LIMIT],
        "total": len(annotated),
        "visible_n": len(visible),
        "counts": counts,
        "more": more,
        "skipped": skipped,
        "show_hidden": show_hidden,
    }


def _query_flags(request: Request) -> tuple[bool, bool]:
    return (
        request.query_params.get("hidden") == "1",
        request.query_params.get("all") == "1",
    )


@router.get("/rank")
async def rank_page(request: Request):
    show_hidden, show_all = _query_flags(request)
    return rendering.page(
        request, "rank.html", {"view": "rank", **_rows(show_hidden, show_all)}
    )


@router.get("/rank/posting/{name}")
async def posting(request: Request, name: str):
    path = _posting_path(name)
    text = path.read_text(encoding="utf-8", errors="replace")
    prof = profile.load_profile(_profile_path())
    # Hits score the full text (same input as the list); the reading pane
    # drops the raw mail frontmatter - headers are noise on screen.
    body = goldenset.sanitize(text)
    return rendering.templates.TemplateResponse(
        request, "_rank_detail.html", {"hits": rank.hit_names(prof, text), "body": body}
    )


@router.post("/rank/track")
async def track_posting(request: Request):
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    name = form["file"][0]
    title = form["title"][0]
    path = _posting_path(name)
    track.add(
        _db_path(),
        str(path),
        title=title,
        status="queued",
        dossier_root=_dossier_root(),
    )
    # Batch triage: stay in the list; the dossier is one click away via the badge.
    return rendering.templates.TemplateResponse(
        request, "_rank_rows.html", _rows(show_hidden=False, show_all=False)
    )


@router.post("/rank/discard")
async def discard_posting(request: Request):
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    path = _posting_path(form["file"][0])
    dest = _inbox_dir() / "discarded"
    dest.mkdir(exist_ok=True)
    path.rename(dest / path.name)
    return rendering.templates.TemplateResponse(
        request, "_rank_rows.html", _rows(show_hidden=False, show_all=False)
    )
