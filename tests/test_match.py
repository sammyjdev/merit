from merit.nodes.match import MATCH_PROMPT, make_match_node
from merit.profile import load_profile
from merit.schemas import ResidueVerdicts, Verdict
from tests.test_profile import FIXTURE


class FakeJudge:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        return self.result


def _demand(name, kind="core"):
    return {"name": name, "kind": kind, "quote": name}


def test_alias_stage_resolves_known_names_without_llm():
    profile = load_profile(FIXTURE)
    judge = FakeJudge(ResidueVerdicts(verdicts=[]))
    node = make_match_node(profile, judge)
    out = node({"demands": [_demand("FastAPI"), _demand("PyTorch")]})
    assert judge.calls == 0
    verdicts = out["verdicts"]
    assert verdicts[0]["verdict"] == "strong" and verdicts[0]["resolved_by"] == "alias"
    assert verdicts[0]["evidence"] == ["api: 40 routes"]
    assert verdicts[1]["verdict"] == "gap"


def test_residue_goes_to_judge():
    profile = load_profile(FIXTURE)
    judged = Verdict(
        demand="Distributed systems", verdict="partial",
        justification="adjacent experience", resolved_by="llm",
    )
    judge = FakeJudge(ResidueVerdicts(verdicts=[judged]))
    node = make_match_node(profile, judge)
    out = node({"demands": [_demand("FastAPI"), _demand("Distributed systems")]})
    assert judge.calls == 1
    assert out["verdicts"][1]["demand"] == "Distributed systems"
    assert out["verdicts"][1]["resolved_by"] == "llm"


def test_prompt_carries_profile_and_residue():
    assert "{profile}" in MATCH_PROMPT and "{residue}" in MATCH_PROMPT
