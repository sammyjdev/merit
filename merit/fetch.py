# merit/fetch.py
"""CLI-side URL fetching. Stdlib only; the graph core never imports this."""
import urllib.request
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import urlparse

MAX_BYTES = 2_000_000


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
    scheme = urlparse(url).scheme
    if scheme not in ("http", "https"):
        raise ValueError(f"unsupported scheme {scheme!r}: only http/https allowed")
    # S310 suppressed on both calls: the scheme allowlist above is the control.
    req = urllib.request.Request(url, headers={"User-Agent": "merit/0.1"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        body = resp.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError(f"response too large: over {MAX_BYTES} bytes")
    return html_to_text(body.decode("utf-8", errors="replace"))
