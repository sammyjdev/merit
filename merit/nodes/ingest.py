"""Normalize already-fetched posting text. Deterministic, no LLM."""
import re

from merit.state import MeritState

MAX_CHARS = 20000


def ingest(state: MeritState) -> dict:
    text = state["posting_text"]
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    collapsed: list[str] = []
    for line in lines:
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)
    return {"posting_text": "\n".join(collapsed).strip()[:MAX_CHARS]}
