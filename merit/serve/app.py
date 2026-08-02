"""Local server shell: FastAPI app factory. Routes render templates and call
existing modules (queue/track/rank/profile) - no business logic here.

Security contract (spec 2026-07-30): localhost only, CSP self, autoescape on,
no state-changing GET.
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from merit.serve.views import dossie, fila, pipeline
from merit.telemetry import setup_tracing

HOST = "127.0.0.1"
CSP = "default-src 'self'"

_PKG_DIR = Path(__file__).parent


def create_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    setup_tracing(app)
    app.mount("/static", StaticFiles(directory=str(_PKG_DIR / "static")), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/")
    async def root(request: Request):
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/fila", status_code=307)

    app.include_router(fila.router)
    app.include_router(pipeline.router)
    app.include_router(dossie.router)
    return app
