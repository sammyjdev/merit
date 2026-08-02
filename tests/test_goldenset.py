# tests/test_goldenset.py
import json

from merit import goldenset

RAW_CORPUS_POSTING = (
    "# Achilles - via Juana Martina Molina\n\n"
    "Senior AI Engineer. RAG e agentes aplicados a dados e risco.\n"
)

RAW_INBOX_POSTING = (
    "---\n"
    "from: Ana Recruiter <inmail-hit-reply@linkedin.com>\n"
    "subject: AI Engineer- Remote- Qubika\n"
    "date: Thu, 18 Jun 2026 09:14:00 +0000\n"
    "message-id: <inmail-0001@lva1.prod.linkedin.com>\n"
    "---\n\n"
    "Hi Sammy, we are hiring an AI Engineer.\n"
)


def test_sanitize_strips_recruiter_name_from_heading():
    clean = goldenset.sanitize(RAW_CORPUS_POSTING)
    assert "Juana" not in clean
    assert "Molina" not in clean
    assert "# Achilles" in clean
    assert "RAG e agentes" in clean


def test_sanitize_strips_mail_frontmatter_entirely():
    clean = goldenset.sanitize(RAW_INBOX_POSTING)
    assert "Ana Recruiter" not in clean
    assert "inmail-hit-reply" not in clean
    assert "message-id" not in clean
    assert "Hi Sammy, we are hiring" in clean


def test_iter_examples_pairs_sanitized_posting_with_reference(tmp_path):
    (tmp_path / "achilles.md").write_text(RAW_CORPUS_POSTING, encoding="utf-8")
    golden = {"achilles.md": {"Python": "strong", "RAG": "strong"}}
    golden_path = tmp_path / "golden.json"
    golden_path.write_text(json.dumps(golden), encoding="utf-8")

    examples = list(goldenset.iter_examples(tmp_path, golden_path))

    assert len(examples) == 1
    ex = examples[0]
    assert "Juana" not in ex["inputs"]["posting"]
    assert ex["outputs"]["verdicts"] == {"Python": "strong", "RAG": "strong"}
    assert ex["metadata"]["file"] == "achilles.md"


def test_agreement_evaluator_scores_fraction_of_matching_demands():
    outputs = {"verdicts": {"python": "strong", "rag": "gap", "aws": "strong"}}
    reference = {"verdicts": {"Python": "strong", "RAG": "strong", "AWS": "strong"}}
    score = goldenset.agreement(outputs, reference)
    assert abs(score - 2 / 3) < 1e-9
