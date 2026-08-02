"""Golden-set tooling for LangSmith: sanitized dataset upload + agreement runs.

Postings carry third-party personal data (recruiter names in headings, mail
frontmatter). Nothing leaves the machine unsanitized - sanitize() runs before
any upload, and the tests pin that contract.

Usage (owner-side, env: LANGSMITH_API_KEY):
    python -m merit.goldenset upload   # create/refresh dataset "merit-golden"
    python -m merit.goldenset run      # LangSmith experiment over the dataset
"""
import json
import re
import sys
from pathlib import Path

DATASET = "merit-golden"
CORPUS = Path("corpus")
GOLDEN = CORPUS / "golden.json"

_VIA_RE = re.compile(r"\s+-\s+via\s+.+$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def sanitize(text: str) -> str:
    text = _FRONTMATTER_RE.sub("", text)
    text = _VIA_RE.sub("", text)
    return text.strip() + "\n"


def iter_examples(corpus_dir: Path, golden_path: Path):
    golden = json.loads(Path(golden_path).read_text(encoding="utf-8"))
    for posting_file, verdicts in golden.items():
        raw = (Path(corpus_dir) / posting_file).read_text(encoding="utf-8")
        yield {
            "inputs": {"posting": sanitize(raw)},
            "outputs": {"verdicts": verdicts},
            "metadata": {"file": posting_file},
        }


def agreement(outputs: dict, reference: dict) -> float:
    got = {k.lower(): v for k, v in outputs["verdicts"].items()}
    want = reference["verdicts"]
    if not want:
        return 1.0
    hits = sum(1 for demand, verdict in want.items() if got.get(demand.lower()) == verdict)
    return hits / len(want)


def _upload() -> None:
    from langsmith import Client

    client = Client()
    if client.has_dataset(dataset_name=DATASET):
        print(f"dataset {DATASET} already exists; leaving it untouched")
        return
    dataset = client.create_dataset(
        dataset_name=DATASET,
        description="MERIT golden set: sanitized postings + 114 human-pinned verdicts",
    )
    examples = list(iter_examples(CORPUS, GOLDEN))
    client.create_examples(
        dataset_id=dataset.id,
        inputs=[e["inputs"] for e in examples],
        outputs=[e["outputs"] for e in examples],
        metadata=[e["metadata"] for e in examples],
    )
    print(f"uploaded {len(examples)} examples to {DATASET}")


def _target(inputs: dict) -> dict:
    from langgraph.checkpoint.memory import MemorySaver

    from merit.graph.build import build_graph
    from merit.models import build_extractor, build_judge, build_writer
    from merit.profile import load_profile

    profile = load_profile("profile/profile.yaml")
    graph = build_graph(profile, build_extractor(), build_judge(), build_writer(), MemorySaver())
    config = {"configurable": {"thread_id": "goldenset"}}
    graph.invoke(
        {"posting_text": inputs["posting"], "posting_meta": {"source": "goldenset"}},
        config,
    )
    verdicts = {v["demand"]: v["verdict"] for v in graph.get_state(config).values["verdicts"]}
    return {"verdicts": verdicts}


def _run() -> None:
    from langsmith import evaluate

    def verdict_agreement(outputs: dict, reference_outputs: dict) -> float:
        return agreement(outputs, reference_outputs)

    result = evaluate(
        _target,
        data=DATASET,
        evaluators=[verdict_agreement],
        experiment_prefix="merit-graph",
        max_concurrency=2,
    )
    print("experiment:", result.experiment_name)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "upload":
        _upload()
    elif cmd == "run":
        _run()
    else:
        sys.exit("usage: python -m merit.goldenset upload|run")
