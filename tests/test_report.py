# tests/test_report.py
from merit.nodes.report import report

VERDICTS = [
    {"demand": "FastAPI", "verdict": "strong", "evidence": ["api: 40 routes"],
     "claims": [], "justification": "profile entry", "resolved_by": "alias"},
    {"demand": "PyTorch", "verdict": "gap", "evidence": [], "claims": [],
     "justification": "no evidence", "resolved_by": "alias"},
]


def test_report_contains_counts_table_and_gaps():
    out = report({"verdicts": VERDICTS, "posting_meta": {"source": "vaga.md"}})
    md = out["report_md"]
    assert "# MERIT fit report" in md
    assert "1 strong / 0 partial / 1 gap" in md
    assert "| FastAPI | strong | api: 40 routes |" in md
    assert "## Gaps" in md and "- PyTorch" in md


def test_report_no_gaps_line():
    out = report({"verdicts": [VERDICTS[0]], "posting_meta": {}})
    assert "No gaps detected." in out["report_md"]
