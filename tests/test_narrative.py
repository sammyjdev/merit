# tests/test_narrative.py
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from merit.nodes.narrative import NARRATIVE_PROMPT, make_narrative_node

VERDICTS = [
    {"demand": "FastAPI", "verdict": "strong", "evidence": ["api: 40 routes"],
     "claims": [], "justification": "", "resolved_by": "alias"},
    {"demand": "PyTorch", "verdict": "gap", "evidence": [], "claims": [],
     "justification": "", "resolved_by": "alias"},
]


def test_narrative_uses_writer_output():
    writer = FakeListChatModel(responses=["- Shipped a 40-route FastAPI service"])
    node = make_narrative_node(writer)
    out = node({"verdicts": VERDICTS, "report_md": "r"})
    assert out == {"narrative_md": "- Shipped a 40-route FastAPI service"}


def test_gap_demands_never_enter_the_prompt(monkeypatch):
    captured = {}

    class Spy:
        def invoke(self, prompt):
            captured["prompt"] = prompt

            class M:
                content = "ok"

            return M()

    make_narrative_node(Spy())({"verdicts": VERDICTS, "report_md": "r"})
    assert "FastAPI" in captured["prompt"] and "PyTorch" not in captured["prompt"]


def test_prompt_forbids_unsupported_claims():
    assert "evidence" in NARRATIVE_PROMPT.lower()
