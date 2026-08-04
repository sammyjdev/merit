"""View: pipeline kanban board for MERIT serve."""
from datetime import UTC, datetime
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from merit import track
from merit.cli import _db_path
from merit.serve import rendering

router = APIRouter()

# Follow-up radar: a process without any logged movement for this many days
# is going cold and gets highlighted (owner-approved 2026-08-04).
COLD_DAYS = 7

ACTIVE_STATUS_SPECS = [
    ("found", "encontrada"),
    ("queued", "na fila"),
    ("applied", "aplicada"),
    ("screening", "triagem"),
    ("interview", "entrevista"),
    ("offer", "oferta"),
]


def _parse_applications(md_text: str) -> list[dict]:
    if md_text == "no applications" or not md_text.strip():
        return []

    rows = []
    lines = md_text.strip().splitlines()
    for line in lines:
        line_str = line.strip()
        if not line_str.startswith("|") or not line_str.endswith("|"):
            continue

        escaped = line_str.replace("\\|", "\x00")
        parts = escaped.split("|")
        if len(parts) < 8:
            continue

        cells = [p.strip().replace("\x00", "|") for p in parts[1:-1]]
        if cells[0] == "id" or cells[0].startswith("---"):
            continue

        try:
            app_id = int(cells[0])
        except ValueError:
            continue

        title = "" if cells[1] == "-" else cells[1]
        company = "" if cells[2] == "-" else cells[2]
        status = "" if cells[3] == "-" else cells[3]
        updated_at = "" if cells[4] == "-" else cells[4]

        rows.append(
            {
                "id": app_id,
                "title": title,
                "company": company,
                "status": status,
                "updated_at": updated_at,
                "idle_days": _idle_days(updated_at),
            }
        )
    return rows


def _idle_days(updated_at: str) -> int | None:
    try:
        return max(0, (datetime.now(UTC) - datetime.fromisoformat(updated_at)).days)
    except ValueError:
        return None


def _build_context(request: Request, db_path: str) -> dict:
    md_text = track.list_markdown(db_path)
    apps = _parse_applications(md_text)

    columns = []
    for status_key, label in ACTIVE_STATUS_SPECS:
        col_apps = [a for a in apps if a["status"] == status_key]
        # coldest first - they are the ones needing a follow-up
        col_apps.sort(key=lambda a: -(a["idle_days"] if a["idle_days"] is not None else -1))
        for a in col_apps:
            a["cold"] = a["idle_days"] is not None and a["idle_days"] >= COLD_DAYS
        columns.append(
            {
                "key": status_key,
                "label": label,
                "count": len(col_apps),
                "apps": col_apps,
            }
        )

    closed_apps = [a for a in apps if a["status"] in ("rejected", "withdrawn")]
    columns.append(
        {
            "key": "closed",
            "label": "encerradas",
            "count": len(closed_apps),
            "apps": closed_apps,
        }
    )

    return {
        "request": request,
        "view": "pipeline",
        "columns": columns,
        "total_apps": len(apps),
        "all_statuses": track.STATUSES,
    }


@router.get("/pipeline")
async def pipeline(request: Request):
    db_path = _db_path()
    context = _build_context(request, db_path)
    return rendering.page(request, "pipeline.html", context)


@router.post("/pipeline/{app_id}/move")
async def move(request: Request, app_id: int):
    # ponytail: parse the urlencoded body with stdlib instead of
    # request.form(), which needs python-multipart (not a project
    # dependency); htmx/tests only ever send urlencoded form data here.
    body = (await request.body()).decode()
    status = dict(parse_qsl(body)).get("status", "")
    db_path = _db_path()
    try:
        track.set_status(db_path, app_id, status)
    except track.TrackError as exc:
        return HTMLResponse(content=str(exc), status_code=422)

    context = _build_context(request, db_path)
    return rendering.page(request, "_pipeline_board.html", context)
