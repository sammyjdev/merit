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
  exit codes. Contains no LLM logic. URL input is fetched by a small adapter in
  the shell (plain HTTP fetch + HTML-to-text); no `langchain-community` loader
  dependency for a single URL. Anything the CLI does, a future FastAPI router
  must be able to do by calling the same graph entrypoint.
- **Graph core** (`merit/graph/`): a LangGraph `StateGraph` over a typed state.
  Edge-IO-free: it receives posting text and a loaded profile, and returns
  state. It does not read files, print, fetch URLs, or know about the CLI; the
  chat models are its only external calls and they are injected as
  dependencies (not stored in checkpointed state), so tests swap them for
  fakes. This boundary is what makes phase 2 (service) and phase 3
  (benchmark) possible without rework.
- **Profile store** (`merit/profile.py` + `profile/profile.yaml`): the
  candidate's skills inventory with evidence pointers. Loaded once per run,
  validated with Pydantic, never mutated by the graph.
- **Model layer** (`merit/models.py`): builds the LangChain chat model from
  env. One place to swap providers.

## The graph

State: a `TypedDict` (the recommended `StateGraph` schema) holding
`posting_text`, `posting_meta`, `demands`, `verdicts`, `report_md`,
`approved`, `narrative_md`, and `profile_hash`. Pydantic stays where it earns
its cost: the `Profile`, `Demand`, and `Verdict` models and every LLM
structured output. Models and other dependencies are injected at graph build
time and never live in the checkpointed state.

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
   template, no LLM.
5. `approval`: the human gate, with the full contract spelled out:
   `interrupt({"report_md": ..., "question": "Approve narrative generation?"})`
   with a JSON-serializable payload; the resume value must be a bool (anything
   else re-interrupts with an error note); `True` routes to `narrative` and
   `False` ends the graph, via `Command(update={"approved": ...}, goto=...)`.
   Resuming uses `graph.invoke(Command(resume=True), config={"configurable":
   {"thread_id": ...}})` with the same thread config. A resumed node restarts
   from its top, so nothing with external effect happens before the
   `interrupt()` call.
6. `narrative`: only reached with approval. Generates tailored CV bullets and
   a short intro note, grounded exclusively in profile evidence (the system
   prompt forbids claiming anything without an evidence pointer - the honesty
   rule as a hard constraint).

Checkpointing: `SqliteSaver` (package `langgraph-checkpoint-sqlite`). The
thread id is a UUID generated on the first run, persisted and printed by the
CLI so `merit resume <id>` continues a paused run (typically at the approval
gate); an optional `--session-id` overrides it. Content-derived ids are
explicitly rejected: two runs of the same posting must not collide. The
state carries `profile_hash` (sha256 of the loaded profile file) so a resume
after approval provably uses the same evidence the report was built from; a
hash mismatch aborts with a clear error instead of silently mixing profiles.

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

- Chat model: `ChatOpenAI` from `langchain-openai`, pointed at an OpenAI-
  compatible endpoint. Default DeepInfra, free-first per house policy;
  `MERIT_MODEL` maps to `model`, `MERIT_API_BASE` to `base_url`,
  `MERIT_API_KEY` to `api_key`.
- Structured output method is explicit, never implicit: `extract` and the LLM
  stage of `match` use `.with_structured_output(..., method="json_schema")`
  (DeepInfra's recommended mode; support is per-model, so the opt-in
  integration test asserts the configured model supports it).
- Temperature 0 for `extract` and `match` (judgments), default for
  `narrative` (writing).
- LangSmith: opt-in, enabled purely by the standard env vars
  (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, and
  `LANGSMITH_ENDPOINT`/`LANGSMITH_WORKSPACE_ID` when applicable); the code
  contains no LangSmith-specific logic. Postings and profile are personal
  data, so the README documents `LANGSMITH_HIDE_INPUTS=true` /
  `LANGSMITH_HIDE_OUTPUTS=true` for runs that must not upload content. The
  12-role corpus is registered as a LangSmith dataset in v0.2.

## Testing

TDD throughout, per house rules. Two strictly separate categories:

**Unit and graph tests (no network, run in CI):**

- `ingest`, `report`, and the alias stage of `match` are deterministic and
  tested directly.
- Text-generating nodes (`narrative`) use `FakeListChatModel`.
- Structured-output nodes (`extract`, LLM stage of `match`) do NOT fake
  `ChatOpenAI` internals: the fakes do not implement
  `with_structured_output()`. Instead, each node receives an injected
  runnable and tests pass a fake that returns the Pydantic object directly.
- Graph-level test: full run on a synthetic posting + synthetic profile with
  scripted fakes, asserting the interrupt fires before `narrative`, that a
  `False` resume ends the run, and that a profile-hash mismatch on resume
  aborts.

**Provider evaluation (opt-in, marked, real network):**

- Golden regression against DeepInfra: replay the 12-role corpus with the
  real profile and assert the human-validated verdicts from 2026-07-28
  (FastAPI covered, LlamaIndex covered, LangChain/LangGraph gap, classic ML
  gap...). This is an evaluation, not a unit test: it is skipped when the
  corpus or key is absent, and asserts verdict agreement, not exact-string
  equality. It also asserts the configured model supports
  `method="json_schema"`.

## Security

Threat model for phase 1, in priority order:

1. **Prompt injection.** The posting is untrusted input that reaches two
   prompts. A hostile posting can instruct the judge to upgrade verdicts or
   fabricate evidence. Structural mitigations: the deterministic alias stage
   bypasses the LLM for known skills, and narrative only uses profile-backed
   evidence. Hard mitigation: the match node post-validates every judged
   verdict - a verdict is accepted only for demands actually sent in the
   residue, and only citing evidence/claim strings that literally exist in
   the profile; anything else is downgraded to `gap` with justification
   `"unverifiable evidence claim rejected"`. Prompts wrap untrusted content
   in explicit data delimiters with an instruction that delimited content is
   data, not instructions.
2. **SSRF / resource exhaustion on URL fetch.** `fetch_posting` validates the
   scheme (http/https only, rejecting `file://` and friends regardless of
   call site) and caps the response at 2 MB.
3. **Secrets and personal data.** Secrets come from env only; `.env`,
   `profile/profile.yaml`, `corpus/`, and `*.db` are gitignored; LangSmith
   masking vars are documented for sensitive runs.
4. **Supply chain / regression.** CI runs the house security gate: ruff with
   the `S` ruleset blocking (tests get a scoped `S101` ignore), gitleaks, and
   pip-audit, plus the offline test suite.

## Decisions

- **D1 CLI-first.** The user lives in the terminal; a service adds surface
  without adding evidence value in phase 1. Revisited in phase 2 by design.
- **D2 LangGraph StateGraph with SqliteSaver and interrupt.** These are the
  idioms that distinguish LangGraph from plain chains; the approval gate is a
  real product need, not a demo.
- **D3 Graph core is edge-IO-free with injected models.** No file, terminal,
  or inbound-HTTP IO inside the graph; chat models are injected dependencies.
  Enables phase 2 (mount in FastAPI) and phase 3 (benchmark harness drives
  the graph directly) without rework, and makes every node testable offline.
- **D4 Deterministic-first matching.** The alias table resolves known names
  before any LLM call: cheaper, reproducible, and it shrinks the surface the
  golden regression has to trust an LLM for.
- **D5 Honesty as a constraint, not a style.** Narrative generation is
  grounded in evidence pointers only; a claim without evidence is a bug.
- **D6 Public repo, private data.** Code public from day 1; profile and
  postings corpus gitignored. Example fixtures keep the repo runnable.
- **D7 Free-provider default.** DeepInfra OpenAI-compatible endpoint, env-
  swappable, matching the house provider policy.
- **D8 Deterministic verdict post-validation.** LLM-judged verdicts are
  filtered by code, not trust: unknown demands dropped, unverifiable evidence
  downgraded to gap. The LLM proposes; the code disposes.
- **D9 House security gate in CI.** ruff `S` blocking + gitleaks + pip-audit,
  the same standard already enforced in axon, glyph, and gnomon.

## Roadmap

- **v0.1 (this spec):** CLI agent, 6-node graph, checkpointing, approval
  gate, LangSmith tracing, golden regression.
- **v0.2 - mail ingestion (repriorized 2026-07-29):** postings arrive by
  email, never by scraping. LinkedIn's terms prohibit automated collection
  and the account is the asset; the compliant channels are the user's own
  inbox. Two adapters: (a) recruiter-message notification emails, which carry
  the message text and feed the full pipeline; (b) job-alert emails, which
  carry only title/company/link and feed a triage queue with deterministic
  keyword prefilter (full match still requires the pasted description).
  IMAP + app password, env-only credentials, Gmail label as the consumption
  contract, synthetic .eml fixtures in tests.
- **v0.25 - evals:** postings corpus as a LangSmith dataset; LLM-as-judge
  scoring of report quality (GNOMON bridge); prompt iteration against the
  dataset instead of vibes.
- **v0.3 - service (approach C):** FastAPI layer mounting the same graph
  (async endpoints, background runs, SSE for progress), authn, Docker
  deploy on the existing Coolify VPS. This is the end-to-end showcase.
- **v1.0 - benchmark (approach 3):** MERIT's graph vs a custom-loop
  implementation on the same corpus, judged by a GNOMON panel, published
  through METRON + evidence-repo like the GLYPH rounds.
