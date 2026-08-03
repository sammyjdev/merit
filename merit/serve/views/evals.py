"""View: evals. Renders local benchmark artifacts (summary.json) - the
credibility scoreboard. Read-only; no network, no LLM."""
import json
import os
from pathlib import Path

from fastapi import APIRouter, Request

from merit.serve import rendering

router = APIRouter()

DEFAULT_SUMMARY = "docs/evals/summary.json"


@router.get("/evals")
async def evals(request: Request):
    path = Path(os.environ.get("MERIT_EVALS_SUMMARY", DEFAULT_SUMMARY))
    summary = None
    if path.is_file():
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            summary = None
    return rendering.page(request, "evals.html", {"view": "evals", "summary": summary})
