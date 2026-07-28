# merit/nodes/narrative.py
"""Generate application material grounded exclusively in covered evidence."""
import json

from merit.state import MeritState

NARRATIVE_PROMPT = """Write tailored CV bullets and a short intro note for this application.

Hard rule: every statement must trace to one of the evidence items below.
A claim without an evidence pointer is a defect. Do not mention skills that
are not listed. Plain hyphens only; no em dashes.

Covered demands with evidence:
{covered}
"""


def make_narrative_node(writer):
    def narrative(state: MeritState) -> dict:
        covered = [v for v in state["verdicts"] if v["verdict"] in ("strong", "partial")]
        prompt = NARRATIVE_PROMPT.format(covered=json.dumps(covered, indent=2))
        return {"narrative_md": writer.invoke(prompt).content}

    return narrative
