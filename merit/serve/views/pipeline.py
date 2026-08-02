"""View: pipeline. Wave 0 stub - the lane owning this view replaces the body.
Routes call existing merit modules only; no SQL, no business logic here."""
from fastapi import APIRouter, Request

from merit.serve import rendering

router = APIRouter()


@router.get("/pipeline")
async def pipeline(request: Request):
    return rendering.page(request, "pipeline.html", {"view": "pipeline"})
