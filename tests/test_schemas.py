import pytest
from pydantic import ValidationError

from merit.schemas import Demand, Demands, Profile, ResidueVerdicts, SkillEntry, Verdict


def test_skill_entry_defaults():
    s = SkillEntry(id="fastapi", name="FastAPI", status="strong")
    assert s.evidence == [] and s.claims == []


def test_profile_aliases_default():
    p = Profile(skills=[SkillEntry(id="x", name="X", status="gap")])
    assert p.aliases == {}


def test_invalid_status_rejected():
    with pytest.raises(ValidationError):
        SkillEntry(id="x", name="X", status="excellent")


def test_verdict_dump_keys():
    v = Verdict(demand="RAG", verdict="strong", justification="ok", resolved_by="alias")
    assert set(v.model_dump()) == {
        "demand", "verdict", "evidence", "claims", "justification", "resolved_by",
    }


def test_demands_container():
    d = Demands(demands=[Demand(name="RAG", kind="core", quote="RAG pipelines")])
    assert d.demands[0].kind == "core"


def test_residue_verdicts_container():
    rv = ResidueVerdicts(verdicts=[])
    assert rv.verdicts == []
