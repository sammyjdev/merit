"""Vagas view: the unified triage surface (IA redesign, owner-approved
2026-08-03). One list answering three questions per posting: where it came
from (inmail = recruiter mail with a body, alerta = job-alert link), how
strong the owner is for it (source-calibrated level, not a raw score), and
where it is going (pipeline state inline when tracked).

Filters: stale (30+ days) gone entirely; on-site and score <= 0 leave the
default list, counted with a ?hidden=1 reveal. ?src=inmail|alerta narrows
by origin.
"""
import math
import os
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request

from merit import goldenset, mail, profile, queue, rank, track
from merit.serve import rendering

router = APIRouter()

VAGAS_LIMIT = 50
STALE_DAYS = 30

# Score ceilings per source: inmail scores the full body, alerta only the
# title - the level bands and the bar normalize across that gap.
CAPS = {"inmail": 20, "alerta": 6}
BANDS = {"inmail": (10, 4), "alerta": (4, 2)}  # (forte >=, medio >=)


def level(source: str, score: int) -> str:
    forte, medio = BANDS[source]
    if score >= forte:
        return "forte"
    if score >= medio:
        return "medio"
    return "fraco"


def bar(source: str, score: int) -> str:
    cap = CAPS[source]
    filled = max(1, math.ceil(5 * min(max(score, 0), cap) / cap)) if score > 0 else 1
    return "█" * filled + "░" * (5 - filled)


def _inbox_dir() -> Path:
    return Path(os.environ.get("MERIT_INBOX", "corpus/inbox"))


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


def _posting_path(name: str) -> Path:
    """Resolve a plain .md filename inside the inbox; anything else is 404."""
    if Path(name).name != name or not name.endswith(".md"):
        raise HTTPException(status_code=404)
    path = _inbox_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return path


def _alert_age(alert_date: str | None) -> int | None:
    if not alert_date:
        return None
    try:
        return max(0, (date.today() - date.fromisoformat(alert_date)).days)
    except ValueError:
        return None


def _inmail_rows(prof, tracked, threads) -> tuple[list[dict], list[str], int]:
    all_rows, skipped = rank.rank_dir(prof, _inbox_dir())
    inbox = _inbox_dir()
    rows = []
    for r in all_rows:
        if r.age_days is not None and r.age_days > STALE_DAYS:
            continue  # stale is gone entirely (owner call 2026-08-03)
        app = tracked.get(str(inbox / r.file))
        if app is None and r.thread and r.thread in threads:
            # A reply inside an already-tracked conversation is not a new vaga.
            app = threads[r.thread]
        rows.append(
            {
                "source": "inmail",
                "title": r.title,
                "company": None,
                "file": r.file,
                "url": None,
                "age_days": r.age_days,
                "score": r.score,
                "workplace": r.workplace,
                "thread": r.thread,
                "app_id": app[0] if app else None,
                "state": app[1] if app else None,
            }
        )
    # One row per conversation: messages sharing a thread collapse to the
    # freshest one (visible in the counters, never a silent drop).
    freshest: dict[str, dict] = {}
    grouped = 0
    deduped = []
    for row in rows:
        tid = row["thread"]
        if not tid:
            deduped.append(row)
            continue
        current = freshest.get(tid)
        if current is None:
            freshest[tid] = row
            deduped.append(row)
        else:
            grouped += 1
            if (row["age_days"] or 0) < (current["age_days"] or 0):
                current.update(row)
    return deduped, skipped, grouped


def _alert_rows(prof, tracked) -> list[dict]:
    rows = []
    for e in queue.load_entries(_queue_path()):
        if queue.is_stale(e, days=STALE_DAYS):
            continue
        score = rank.score_text(prof, e.title)[3] if prof else 0
        app = tracked.get(e.url)
        rows.append(
            {
                "source": "alerta",
                "title": e.title,
                "company": e.company,
                "file": None,
                "url": e.url,
                "age_days": _alert_age(e.alert_date),
                "score": score,
                "workplace": rank.classify_workplace(f"{e.title} {e.company or ''}"),
                "thread": None,
                "app_id": app[0] if app else None,
                "state": app[1] if app else None,
            }
        )
    return rows


def _threads_status(tracked: dict[str, tuple[int, str]]) -> dict[str, tuple[int, str]]:
    """thread_id -> (app_id, status), derived from the tracked map's ids."""
    by_id = {app_id: (app_id, status) for app_id, status in tracked.values()}
    return {
        tid: by_id[app_id]
        for tid, app_id in track.threads(_db_path()).items()
        if app_id in by_id
    }


def _reason(row: dict) -> str | None:
    if row["app_id"] is not None:
        return "acompanhando"
    if row["workplace"] == "onsite":
        return "on-site"
    if row["score"] <= 0:
        return "sem aderencia"
    return None


def _rows(show_hidden: bool, show_all: bool, src: str | None) -> dict:
    prof = profile.load_profile(_profile_path()) if Path(_profile_path()).is_file() else None
    tracked = track.sources_status(_db_path())
    threads = _threads_status(tracked)
    inmails, skipped, grouped = _inmail_rows(prof, tracked, threads) if prof else ([], [], 0)
    alerts = _alert_rows(prof, tracked)
    rows = inmails + alerts

    counts = {
        "inmail": len(inmails),
        "alerta": len(alerts),
        "onsite": 0,
        "weak": 0,
        "tracked": 0,
        "grouped": grouped,
    }
    for row in rows:
        row["reason"] = _reason(row)
        row["level"] = level(row["source"], row["score"])
        row["bar"] = bar(row["source"], row["score"])
        row["fraction"] = min(max(row["score"], 0), CAPS[row["source"]]) / CAPS[row["source"]]
        if row["reason"] == "acompanhando":
            counts["tracked"] += 1
        elif row["reason"] == "on-site":
            counts["onsite"] += 1
        elif row["reason"] == "sem aderencia":
            counts["weak"] += 1

    if src in ("inmail", "alerta"):
        rows = [r for r in rows if r["source"] == src]
    rows.sort(key=lambda r: (-r["fraction"], r["age_days"] if r["age_days"] is not None else 999))

    visible = [r for r in rows if r["reason"] is None]
    displayed = rows if show_hidden else visible
    return {
        "rows": displayed if show_all else displayed[:VAGAS_LIMIT],
        "more": 0 if show_all else max(0, len(displayed) - VAGAS_LIMIT),
        "total": len(rows),
        "visible_n": len(visible),
        "counts": counts,
        "skipped": skipped,
        "show_hidden": show_hidden,
        "src": src or "",
    }


def _flags(request: Request) -> tuple[bool, bool, str | None]:
    q = request.query_params
    return (q.get("hidden") == "1", q.get("all") == "1", q.get("src"))


@router.get("/vagas")
async def vagas_page(request: Request):
    show_hidden, show_all, src = _flags(request)
    return rendering.page(
        request, "vagas.html", {"view": "vagas", **_rows(show_hidden, show_all, src)}
    )


@router.get("/vagas/posting/{name}")
async def posting(request: Request, name: str):
    path = _posting_path(name)
    text = path.read_text(encoding="utf-8", errors="replace")
    prof = profile.load_profile(_profile_path())
    return rendering.templates.TemplateResponse(
        request,
        "_vagas_detail.html",
        {"hits": rank.hit_names(prof, text), "body": goldenset.sanitize(text)},
    )


def _rows_partial(request: Request):
    return rendering.templates.TemplateResponse(
        request, "_vagas_rows.html", _rows(show_hidden=False, show_all=False, src=None)
    )


@router.post("/vagas/track")
async def track_vaga(request: Request):
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    title = form["title"][0]
    thread = None
    if "file" in form:
        path = _posting_path(form["file"][0])
        source = str(path)
        company = None
        # Thread id links future recruiter replies straight into the dossier.
        thread = mail.thread_id(path.read_text(encoding="utf-8", errors="replace"))
    else:
        source = form["url"][0]
        company = form.get("company", [""])[0] or None
    track.add(
        _db_path(),
        source,
        title=title,
        company=company,
        status="queued",
        dossier_root=_dossier_root(),
        thread_id=thread,
    )
    return _rows_partial(request)


@router.post("/vagas/discard")
async def discard_vaga(request: Request):
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    if "file" in form:
        path = _posting_path(form["file"][0])
        dest = _inbox_dir() / "discarded"
        dest.mkdir(exist_ok=True)
        path.rename(dest / path.name)
    else:
        queue.discard(_queue_path(), form["url"][0])
    return _rows_partial(request)
