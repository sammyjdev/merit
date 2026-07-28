"""Two-stage matching: deterministic alias resolution, then LLM judgment on the residue."""
import json

from merit.profile import resolve
from merit.schemas import Profile, Verdict
from merit.state import MeritState

MATCH_PROMPT = """You judge whether a candidate profile covers each demanded skill.

For every demand below, return a verdict: strong, partial, or gap.
- strong: the profile has direct evidence for the demand.
- partial: adjacent or transferable evidence, named explicitly.
- gap: no honest evidence. Never inflate; an unsupported claim is a defect.
Set resolved_by to "llm" and cite profile evidence strings verbatim when used.

Candidate profile (skills with status and evidence):
{profile}

Demands to judge:
{residue}
"""


def make_match_node(profile: Profile, judge):
    def match(state: MeritState) -> dict:
        resolved: list[dict] = []
        residue: list[dict] = []
        for demand in state["demands"]:
            entry = resolve(profile, demand["name"])
            if entry is None:
                residue.append(demand)
                continue
            resolved.append(
                Verdict(
                    demand=demand["name"],
                    verdict=entry.status,
                    evidence=entry.evidence,
                    claims=entry.claims,
                    justification=f"profile entry '{entry.id}' ({entry.status})",
                    resolved_by="alias",
                ).model_dump()
            )
        judged: list[dict] = []
        if residue:
            prompt = MATCH_PROMPT.format(
                profile=profile.model_dump_json(indent=2),
                residue=json.dumps(residue, indent=2),
            )
            judged = [v.model_dump() for v in judge.invoke(prompt).verdicts]
        return {"verdicts": resolved + judged}

    return match
