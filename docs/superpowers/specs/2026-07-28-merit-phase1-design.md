# MERIT - Phase 1 design

**MERIT: Matching Evidence against Role & Interview Targets.**

An agent that reads a job posting, matches its demands against a versioned
profile backed by an evidence ledger, and produces an honest fit report plus,
under explicit human approval, tailored application material. It automates the
manual 12-role skills-gap analysis performed on 2026-07-27/28 and uses that
validated analysis as its golden regression suite.

Phase 1 is a CLI tool built on LangGraph. Later phases (service, benchmark)
are on the roadmap below; this spec covers phase 1 only.

## Goals

- A `merit match <posting>` command that turns a job posting (file, stdin, or
  URL) into a fit report: per-skill verdicts (strong / partial / gap) with the
  evidence pointer for every non-gap verdict, an overall summary, and honest
  gaps stated without inflation.
- A human-in-the-loop step: narrative material (CV bullets, intro note) is
  generated only after the user approves the fit report, via a LangGraph
  interrupt.
- Resumable sessions: a posting analysis can be interrupted and resumed
  (LangGraph checkpointing).
- Traceable runs: every run traced in LangSmith when the env is configured.
- A test suite where every node is covered without network access, plus a
  golden regression that replays the 12-role corpus and asserts the
  human-validated verdicts.

## Non-goals (phase 1)

- No web UI, no HTTP service (phase 2).
- No job-board scraping or bulk discovery; input is one posting the user
  already has.
- No automatic application or message sending. MERIT never contacts anyone.
- No model fine-tuning and no local model hosting.

## System design

Three components with hard boundaries:

```
+------------------+     +----------------------+     +------------------+
| CLI shell        | --> | Graph core           | --> | Profile store    |
| (typer, IO only) |     | (LangGraph, pure)    |     | (YAML, read-only |
|                  |     |                      |     |  during a run)   |
+------------------+     +----------------------+     +------------------+
                                   |
                                   v
                         +----------------------+
                         | Model layer          |
                         | (LangChain chat      |
                         |  model, OpenAI-      |
                         |  compatible endpoint)|
                         +----------------------+
```

- **CLI shell** (`merit/cli.py`): argument parsing, file/URL loading, printing,
  exit codes. Contains no LLM logic. Anything the CLI does, a future FastAPI
  router must be able to do by calling the same graph entrypoint.
- **Graph core** (`merit/graph/`): a LangGraph `StateGraph` over a typed state.
  Pure with respect to IO: it receives posting text and a loaded profile,
  and returns state. It does not read files, print, or know about the CLI.
  This boundary is what makes phase 2 (service) and phase 3 (benchmark)
  possible without rework.
- **Profile store** (`merit/profile.py` + `profile/profile.yaml`): the
  candidate's skills inventory with evidence pointers. Loaded once per run,
  validated with Pydantic, never mutated by the graph.
- **Model layer** (`merit/models.py`): builds the LangChain chat model from
  env. One place to swap providers.

## The graph

State (Pydantic): `posting_text`, `posting_meta`, `demands` (extracted skills
with seniority/priority), `verdicts` (per-demand match results), `report_md`,
`approved` (bool), `narrative_md`.

Nodes:

1. `ingest`: normalize already-fetched posting text (strip boilerplate,
   collapse whitespace, cap length). Deterministic, no LLM. Fetching is the
   CLI shell's job: URL input goes through a LangChain document loader in the
   shell, and the graph only ever receives text, keeping the core IO-pure.
2. `extract`: structured output (Pydantic schema via LangChain) listing
   demanded skills, each with: name, kind (core / nice-to-have), and the
   quote from the posting that demands it. The quote requirement keeps the
   extraction auditable.
3. `match`: for each demand, match against the profile. Two-stage: a
   deterministic alias table resolves exact/known names first (FastAPI,
   LangGraph, pgvector...); the LLM only judges the residue (fuzzy or
   compound demands). Output per demand: verdict (strong / partial / gap),
   evidence pointer (profile entry id, and claim id when the profile entry
   carries one), one-line justification.
4. `report`: render the fit report markdown from the verdicts. Deterministic
   template, no LLM. Ends with `interrupt()` so the run pauses for approval.
5. `narrative`: only reached after the user resumes with approval. Generates
   tailored CV bullets and a short intro note, grounded exclusively in
   profile evidence (the system prompt forbids claiming anything without an
   evidence pointer - the honesty rule as a hard constraint).

Checkpointing: `SqliteSaver` keyed by a thread id derived from the posting, so
`merit resume <id>` continues a paused run (typically at the approval gate).

## Profile schema

`profile/profile.yaml` (gitignored; `profile/profile.example.yaml` committed):

```yaml
skills:
  - id: fastapi
    name: FastAPI
    status: strong
    evidence:
      - "PitStopOS: 49-route production API"
      - "aerus: 32 routes + token-auth WebSocket"
  - id: llamaindex
    name: LlamaIndex
    status: strong
    evidence:
      - "METRON code-retrieval-roundtable adapter"
    claims: [C-GLYPH-EXT-002, C-GLYPH-EXT-003]
  - id: pytorch
    name: PyTorch
    status: gap
aliases:
  "REST APIs": fastapi
```

The real profile is personal data and stays out of the public repo, along with
the postings corpus (recruiter names). Tests commit small synthetic fixtures;
the golden 12-role corpus lives locally under `corpus/` (gitignored).

## Models and observability

- Chat model through LangChain's OpenAI-compatible client. Default endpoint
  DeepInfra, free-first per house policy; all of endpoint, key, and model name
  come from env (`MERIT_MODEL`, `MERIT_API_BASE`, `MERIT_API_KEY`).
- Temperature 0 for `extract` and `match` (judgments), default for
  `narrative` (writing).
- LangSmith: enabled purely by the standard `LANGSMITH_*` env vars; the code
  contains no LangSmith-specific logic. The 12-role corpus is registered as a
  LangSmith dataset in v0.2.

## Testing

TDD throughout, per house rules.

- Node-level tests with LangChain fake chat models (no network). `ingest`,
  `report`, and the alias stage of `match` are deterministic and tested
  directly.
- Graph-level test: full run on a synthetic posting + synthetic profile with
  a scripted fake model, asserting the interrupt fires before `narrative`.
- Golden regression (local, marked, skipped when corpus absent): replay the
  12-role corpus against the real profile and assert the human-validated
  verdicts from 2026-07-28 (FastAPI covered, LlamaIndex covered,
  LangChain/LangGraph gap, classic ML gap...).

## Decisions

- **D1 CLI-first.** The user lives in the terminal; a service adds surface
  without adding evidence value in phase 1. Revisited in phase 2 by design.
- **D2 LangGraph StateGraph with SqliteSaver and interrupt.** These are the
  idioms that distinguish LangGraph from plain chains; the approval gate is a
  real product need, not a demo.
- **D3 Graph core is IO-pure.** Enables phase 2 (mount in FastAPI) and
  phase 3 (benchmark harness drives the graph directly) without rework.
- **D4 Deterministic-first matching.** The alias table resolves known names
  before any LLM call: cheaper, reproducible, and it shrinks the surface the
  golden regression has to trust an LLM for.
- **D5 Honesty as a constraint, not a style.** Narrative generation is
  grounded in evidence pointers only; a claim without evidence is a bug.
- **D6 Public repo, private data.** Code public from day 1; profile and
  postings corpus gitignored. Example fixtures keep the repo runnable.
- **D7 Free-provider default.** DeepInfra OpenAI-compatible endpoint, env-
  swappable, matching the house provider policy.

## Roadmap

- **v0.1 (this spec):** CLI agent, 5-node graph, checkpointing, approval
  gate, LangSmith tracing, golden regression.
- **v0.2 - evals:** 12-role corpus as a LangSmith dataset; LLM-as-judge
  scoring of report quality (GNOMON bridge); prompt iteration against the
  dataset instead of vibes.
- **v0.3 - service (approach C):** FastAPI layer mounting the same graph
  (async endpoints, background runs, SSE for progress), authn, Docker
  deploy on the existing Coolify VPS. This is the end-to-end showcase.
- **v1.0 - benchmark (approach 3):** MERIT's graph vs a custom-loop
  implementation on the same corpus, judged by a GNOMON panel, published
  through METRON + evidence-repo like the GLYPH rounds.
