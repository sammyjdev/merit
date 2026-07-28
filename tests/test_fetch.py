# tests/test_fetch.py
from merit.fetch import html_to_text

HTML = """
<html><head><style>.x{color:red}</style><script>var a=1;</script></head>
<body><h1>Senior AI Engineer</h1><p>Build RAG pipelines.</p></body></html>
"""


def test_html_to_text_strips_script_and_style():
    text = html_to_text(HTML)
    assert "Senior AI Engineer" in text
    assert "Build RAG pipelines." in text
    assert "color:red" not in text and "var a=1" not in text
