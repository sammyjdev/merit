"""Shared template rendering helper (single Jinja2 env, autoescape on)."""
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def page(request: Request, template: str, context: dict):
    return templates.TemplateResponse(request, template, context)
