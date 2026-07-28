# tests/test_graph.py
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from merit.graph.build import build_graph
from merit.profile import load_profile
from merit.schemas import ResidueVerdicts
from tests.test_profile import FIXTURE


class FakeStructured:
    def __init__(self, result):
        self.result = result

    def invoke(self, prompt):
        return self.result


class FakeWriter:
    def invoke(self, prompt):
        class M:
            content = "- bullet grounded in evidence"

        return M()


def _graph():
    from merit.schemas import Demand, Demands

    profile = load_profile(FIXTURE)
    extractor = FakeStructured(
        Demands(demands=[Demand(name="FastAPI", kind="core", quote="FastAPI")])
    )
    judge = FakeStructured(ResidueVerdicts(verdicts=[]))
    return build_graph(profile, extractor, judge, FakeWriter(), MemorySaver())


def _config():
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def test_run_pauses_at_approval_before_narrative():
    graph, config = _graph(), _config()
    result = graph.invoke({"posting_text": "FastAPI role", "posting_meta": {}}, config)
    assert "__interrupt__" in result
    state = graph.get_state(config)
    assert state.values.get("narrative_md") is None
    assert "# MERIT fit report" in state.values["report_md"]


def test_approve_true_generates_narrative():
    graph, config = _graph(), _config()
    graph.invoke({"posting_text": "FastAPI role", "posting_meta": {}}, config)
    result = graph.invoke(Command(resume=True), config)
    assert result["approved"] is True
    assert result["narrative_md"] == "- bullet grounded in evidence"


def test_approve_false_ends_without_narrative():
    graph, config = _graph(), _config()
    graph.invoke({"posting_text": "FastAPI role", "posting_meta": {}}, config)
    result = graph.invoke(Command(resume=False), config)
    assert result["approved"] is False
    assert "narrative_md" not in result


def test_non_bool_resume_reinterrupts():
    graph, config = _graph(), _config()
    graph.invoke({"posting_text": "FastAPI role", "posting_meta": {}}, config)
    result = graph.invoke(Command(resume="yes"), config)
    assert "__interrupt__" in result
