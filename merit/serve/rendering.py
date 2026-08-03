"""Shared template rendering helper (single Jinja2 env, autoescape on)."""
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


_nav_cache: dict = {}


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def nav_counts() -> dict | None:
    """Visible-work badges for the topbar. Never breaks a page render: any
    failure (missing profile, empty stores) degrades to no badges.
    Cached on (paths, mtimes) - the inbox dir mtime moves on ingest/discard,
    the db on track writes, the queue file on append/discard."""
    # Lazy imports: views import this module, so top-level would be circular.
    from merit import track
    from merit.serve.views import fila, rank

    try:
        inbox = rank._inbox_dir()
        queue_path = fila._queue_path()
        db = Path(rank._db_path())
        key = (
            str(inbox), _mtime(inbox),
            str(queue_path), _mtime(queue_path),
            str(db), _mtime(db),
            rank._profile_path(),
        )
        if _nav_cache.get("key") != key:
            _nav_cache["value"] = {
                "fila": fila._rows(show_hidden=False)["visible_n"],
                "rank": rank._rows(show_hidden=False, show_all=False)["visible_n"],
                "pipeline": track.count_active(str(db)),
            }
            _nav_cache["key"] = key
        return _nav_cache["value"]
    except Exception:
        return None


def page(request: Request, template: str, context: dict):
    return templates.TemplateResponse(request, template, {"nav": nav_counts(), **context})
