"""View: dossie. Wave 0 stub - the lane owning this view replaces the body.
Routes call existing merit modules only; no SQL, no business logic here."""
from fastapi import APIRouter, Request

from merit.serve import rendering

router = APIRouter()


@router.get("/dossie")
async def dossie_index(request: Request):
    return rendering.page(request, "dossie.html", {"view": "dossie", "app_id": None})


@router.get("/dossie/{app_id}")
async def dossie(request: Request, app_id: int):
    return rendering.page(request, "dossie.html", {"view": "dossie", "app_id": app_id})
