# merit/queue.py
"""Job-alert queue: HTML digest parsing, hot/cold prefilter, flat JSON store.
Stdlib only - no merit.* imports, no LLM/network calls."""
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

QUEUE_PATH = Path("corpus/queue.json")
JOB_URL_MARKER = "/jobs/view/"

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Entry:
    title: str
    company: str | None
    url: str
    alert_date: str
    location: str | None = None  # ponytail: never populated; real digest carries no location


def _sanitize(text: str) -> str:
    return _CONTROL_CHARS.sub("", text).strip()


class _AlertParser(HTMLParser):
    """An eligible <a> opens a title; the first non-empty text chunk after its
    closing tag (before the next <a> or end of doc) becomes the company."""

    def __init__(self) -> None:
        super().__init__()
        self.candidates: list[dict] = []
        self._current: dict | None = None
        self._collecting_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._current = None
        self._collecting_title = False
        href = dict(attrs).get("href") or ""
        if href.startswith("https://") and JOB_URL_MARKER in href:
            candidate = {"href": href, "title_parts": [], "company": None}
            self.candidates.append(candidate)
            self._current = candidate
            self._collecting_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._collecting_title = False

    def handle_data(self, data: str) -> None:
        if self._collecting_title and self._current is not None:
            self._current["title_parts"].append(data)
        elif self._current is not None and self._current["company"] is None:
            chunk = _sanitize(data)
            if chunk:
                self._current["company"] = chunk


def parse_alert(html: str, alert_date: str) -> list[Entry]:
    parser = _AlertParser()
    parser.feed(html)
    entries = []
    for candidate in parser.candidates:
        title = _sanitize("".join(candidate["title_parts"]))
        if not title:
            continue
        entries.append(
            Entry(
                title=title,
                company=candidate["company"],
                url=_sanitize(candidate["href"]),
                alert_date=alert_date,
            )
        )
    return entries


def is_hot(title: str, terms: Iterable[str]) -> bool:
    lowered = title.lower()
    return any(term.lower() in lowered for term in terms)


def dedupe_key(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def load_entries(path: Path) -> list[Entry]:
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [Entry(**row) for row in rows]


def append_entries(new: Iterable[Entry], path: Path) -> list[Entry]:
    existing = load_entries(path)
    seen_keys = {dedupe_key(e.url) for e in existing}
    added: list[Entry] = []
    for entry in new:
        key = dedupe_key(entry.url)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        added.append(entry)
    if not added:
        return []

    rows = [
        {
            "title": e.title,
            "company": e.company,
            "url": e.url,
            "alert_date": e.alert_date,
            "location": e.location,
        }
        for e in (existing + added)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_path.chmod(0o600)
    tmp_path.replace(path)
    return added
