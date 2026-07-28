# tests/test_ingest.py
from merit.nodes.ingest import MAX_CHARS, ingest


def test_collapses_whitespace_and_blank_lines():
    raw = "Senior  AI\t Engineer\n\n\n\nRemote   role\n"
    # Runs of blank lines collapse to exactly one, preserving paragraph boundaries.
    assert ingest({"posting_text": raw}) == {"posting_text": "Senior AI Engineer\n\nRemote role"}


def test_caps_length():
    out = ingest({"posting_text": "x" * (MAX_CHARS + 5000)})
    assert len(out["posting_text"]) == MAX_CHARS
