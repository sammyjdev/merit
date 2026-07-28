"""Graph state. JSON-serializable values only; models are injected, never stored."""
from typing import TypedDict


class MeritState(TypedDict, total=False):
    posting_text: str
    posting_meta: dict
    demands: list[dict]
    verdicts: list[dict]
    report_md: str
    approved: bool
    narrative_md: str
    profile_hash: str
