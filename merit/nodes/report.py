# merit/nodes/report.py
"""Render the fit report. Deterministic template, no LLM."""
from merit.state import MeritState


def report(state: MeritState) -> dict:
    verdicts = state["verdicts"]
    source = state.get("posting_meta", {}).get("source", "posting")
    keys = ("strong", "partial", "gap")
    counts = {k: sum(1 for v in verdicts if v["verdict"] == k) for k in keys}
    lines = [
        "# MERIT fit report",
        "",
        f"Source: {source}",
        (
            f"Coverage: {counts['strong']} strong / {counts['partial']} partial / "
            f"{counts['gap']} gap (of {len(verdicts)} demands)"
        ),
        "",
        "| Demand | Verdict | Evidence |",
        "|---|---|---|",
    ]
    for v in verdicts:
        evidence = "; ".join(v["evidence"] + v["claims"]) or "-"
        lines.append(f"| {v['demand']} | {v['verdict']} | {evidence} |")
    gaps = [v["demand"] for v in verdicts if v["verdict"] == "gap"]
    lines += ["", "## Gaps", ""]
    lines += [f"- {g}" for g in gaps] if gaps else ["No gaps detected."]
    return {"report_md": "\n".join(lines)}
