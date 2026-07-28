# merit/fetch.py
"""CLI-side URL fetching. Stdlib only; the graph core never imports this."""
import urllib.request
from html.parser import HTMLParser
from typing import ClassVar


class _TextExtractor(HTMLParser):
    _SKIP: ClassVar[set[str]] = {"script", "style"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self.chunks.append(data.strip())


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return "\n".join(parser.chunks)


def fetch_posting(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "merit/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return html_to_text(resp.read().decode("utf-8", errors="replace"))
