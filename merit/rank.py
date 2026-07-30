"""Stage-1 deterministic batch scoring: scan a directory of postings against a
profile's alias table and skill names. No LLM, no network, no persistence -
reconnaissance only, so the owner can pick which postings deserve `merit match`.
"""
import re
from pathlib import Path
from typing import NamedTuple

from merit.profile import resolve
from merit.schemas import Profile

DEFAULT_TOP = 20
WEIGHTS = {"strong": 2, "partial": 1, "gap": -1}

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_SUBJECT_RE = re.compile(r"^subject:[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_HEADING_RE = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.MULTILINE)


class Row(NamedTuple):
    file: str
    title: str
    strong: int
    partial: int
    gap: int
    score: int


def extract_title(text: str, fallback: str) -> str:
    frontmatter = _FRONTMATTER_RE.match(text)
    if frontmatter:
        subject = _SUBJECT_RE.search(frontmatter.group(1))
        if subject and subject.group(1).strip():
            return subject.group(1).strip()
    heading = _HEADING_RE.search(text)
    if heading:
        return heading.group(1).strip()
    return fallback


def _compiled_terms(profile: Profile) -> list[tuple[str, re.Pattern[str]]]:
    terms = {s.name for s in profile.skills} | set(profile.aliases.keys())
    return [
        (term, re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE))
        for term in terms
    ]


def score_text(
    profile: Profile,
    text: str,
    _terms: list[tuple[str, re.Pattern[str]]] | None = None,
) -> tuple[int, int, int, int]:
    """Return (strong, partial, gap, score) for raw posting text against profile."""
    terms = _terms if _terms is not None else _compiled_terms(profile)
    # ponytail: verbatim term scan, dedup per skill. No stemming/splitting - the
    # alias table is the tuning knob.
    hits = {}
    for term, pattern in terms:
        if pattern.search(text):
            entry = resolve(profile, term)
            if entry is not None:
                hits[entry.id] = entry
    strong = sum(1 for e in hits.values() if e.status == "strong")
    partial = sum(1 for e in hits.values() if e.status == "partial")
    gap = sum(1 for e in hits.values() if e.status == "gap")
    score = WEIGHTS["strong"] * strong + WEIGHTS["partial"] * partial + WEIGHTS["gap"] * gap
    return strong, partial, gap, score


def rank_dir(profile: Profile, directory: Path) -> tuple[list[Row], list[str]]:
    terms = _compiled_terms(profile)
    rows: list[Row] = []
    skipped: list[str] = []
    for path in sorted(directory.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            skipped.append(f"{path.name}: {exc}")
            continue
        strong, partial, gap, score = score_text(profile, text, terms)
        title = extract_title(text, path.stem)
        rows.append(Row(path.name, title, strong, partial, gap, score))
    rows.sort(key=lambda r: (-r.score, r.file))
    return rows, skipped


def render(rows: list[Row], skipped: list[str], top: int = DEFAULT_TOP) -> str:
    shown = rows[:top] if top > 0 else rows
    lines = [
        "# MERIT rank",
        "",
        f"Postings: {len(rows)} scored, {len(shown)} shown, {len(skipped)} skipped",
        "",
        "| File | Title | Strong | Partial | Gap | Score |",
        "|---|---|---|---|---|---|",
    ]
    for r in shown:
        title = r.title.replace("|", "\\|")
        lines.append(f"| {r.file} | {title} | {r.strong} | {r.partial} | {r.gap} | {r.score} |")
    if skipped:
        lines.append("")
        lines.append("## Skipped")
        lines.append("")
        lines.extend(f"- {s}" for s in skipped)
    return "\n".join(lines)
