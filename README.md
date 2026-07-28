# MERIT

MERIT = Matching Evidence against Role & Interview Targets. A CLI that turns a job posting into an evidence-grounded fit report and, behind a human approval gate, tailored application material.

## Install

```bash
pip install -e '.[dev]'
```

Python >= 3.11 is required.

## Quickstart

```bash
merit match vaga.md
```

The input can also be a URL or `-` for stdin. The command prints the fit report, `Session: <id>`, and the resume hint. Approve or reject tailored material with:

```bash
merit resume <id> --approve
merit resume <id> --reject
```

If `profile/profile.yaml` changed since the report, `merit resume` exits 2 and asks you to re-run `merit match`. The default profile path is `profile/profile.yaml`; `profile/profile.example.yaml` is the template.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MERIT_MODEL` | no default, required | Chat model name |
| `MERIT_API_BASE` | `https://api.deepinfra.com/v1/openai` | OpenAI-compatible API base URL |
| `MERIT_API_KEY` | no default, required | Provider API key |
| `MERIT_DB` | `~/.merit/merit.db` | SQLite checkpoint database path |

## LangSmith tracing

Tracing is opt-in and uses no LangSmith-specific code in the repo. Enable it purely with `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, and `LANGSMITH_ENDPOINT`. Postings and the profile are personal data, so set `LANGSMITH_HIDE_INPUTS=true` and `LANGSMITH_HIDE_OUTPUTS=true` for runs whose content must not be uploaded.

## Testing

`pytest -q` runs the offline suite with no network and deselects the provider marker. `pytest -m provider -q` runs the opt-in golden evaluation and needs `MERIT_API_KEY` plus a local `corpus/golden.json`.

## The honesty rule

Every statement in generated material must trace to a profile evidence item. A claim without an evidence pointer is a defect, not a style choice. LLM-judged verdicts are post-validated by code: verdicts for demands that were not asked about are dropped, and strong/partial verdicts citing evidence not present in the profile are downgraded to gap.

## Roadmap

- **v0.1:** CLI agent, 6-node graph, checkpointing, approval gate, LangSmith tracing, golden regression.
- **v0.2 - evals:** 12-role corpus as a LangSmith dataset; LLM-as-judge scoring of report quality via the GNOMON bridge; prompt iteration against the dataset instead of vibes.
- **v0.3 - service:** FastAPI layer mounting the same graph with async endpoints, background runs, SSE for progress, authn, and Docker deployment on the existing Coolify VPS.
- **v1.0 - benchmark:** MERIT's graph versus a custom-loop implementation on the same corpus, judged by a GNOMON panel and published through METRON plus an evidence repository like the GLYPH rounds.
