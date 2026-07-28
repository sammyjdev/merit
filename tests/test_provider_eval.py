"""Opt-in golden evaluation against the real provider and the local corpus.

Run: pytest -m provider -q  (requires MERIT_MODEL/MERIT_API_KEY and corpus/)
Asserts verdict agreement with the human-validated 2026-07-28 analysis,
never exact strings. This is an evaluation, not a unit test.
"""
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.provider

CORPUS = Path(__file__).parent.parent / "corpus"
GOLDEN = CORPUS / "golden.json"  # {"<posting-file>": {"<demand>": "strong|partial|gap"}}


@pytest.mark.skipif(
    not (GOLDEN.exists() and os.environ.get("MERIT_API_KEY")),
    reason="corpus or provider credentials absent",
)
def test_golden_verdicts_agree():
    from langgraph.checkpoint.memory import MemorySaver

    from merit.graph.build import build_graph
    from merit.models import build_extractor, build_judge, build_writer
    from merit.profile import load_profile

    profile = load_profile("profile/profile.yaml")
    golden = json.loads(GOLDEN.read_text())
    disagreements = []
    for posting_file, expected in golden.items():
        graph = build_graph(
            profile, build_extractor(), build_judge(), build_writer(), MemorySaver()
        )
        config = {"configurable": {"thread_id": posting_file}}
        graph.invoke(
            {
                "posting_text": (CORPUS / posting_file).read_text(),
                "posting_meta": {"source": posting_file},
            },
            config,
        )
        verdicts = {
            v["demand"].lower(): v["verdict"]
            for v in graph.get_state(config).values["verdicts"]
        }
        for demand, want in expected.items():
            got = verdicts.get(demand.lower())
            if got != want:
                disagreements.append(f"{posting_file}: {demand} want={want} got={got}")
    agreement = 1 - len(disagreements) / max(1, sum(len(v) for v in golden.values()))
    assert agreement >= 0.8, f"agreement {agreement:.0%}\n" + "\n".join(disagreements)
