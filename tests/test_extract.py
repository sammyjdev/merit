from merit.nodes.extract import EXTRACT_PROMPT, make_extract_node
from merit.schemas import Demand, Demands


class FakeExtractor:
    def __init__(self, result):
        self.result = result
        self.last_prompt = None

    def invoke(self, prompt):
        self.last_prompt = prompt
        return self.result


def test_extract_node_returns_demand_dicts():
    fake = FakeExtractor(Demands(demands=[Demand(name="RAG", kind="core", quote="build RAG")]))
    node = make_extract_node(fake)
    out = node({"posting_text": "We need someone to build RAG pipelines."})
    assert out == {"demands": [{"name": "RAG", "kind": "core", "quote": "build RAG"}]}
    assert "build RAG pipelines" in fake.last_prompt


def test_prompt_demands_quotes():
    assert "quote" in EXTRACT_PROMPT.lower()
