# MERIT backlog and next steps

Status snapshot (2026-07-29): phase 1 sealed. Six-node graph, CLI, security
hardening, and CI gate are on master; the golden evaluation passed (agreement
>= 80% with the human-validated verdict set, 29 postings / 114 pinned
verdicts, 58-minute provider run surviving overload windows). Mail ingestion
tracer (recruiter messages) is implemented and waiting on review.

## Awaiting the owner

- [ ] Review and merge PR #8 (mail ingestion tracer, issue #6). CI green,
      quench 9/9, both reviewers approved.
- [ ] Gmail app password in `.env` (`MERIT_IMAP_USER` / `MERIT_IMAP_PASSWORD`).
      Unblocks the operational validation of `merit ingest-mail`.
- [ ] Let the recalibrated LinkedIn job alerts accumulate a few days of real
      email under the `merit` label (feeds issue #7 with real fixture shapes).
- [ ] LinkedIn skills update: LangGraph and LangChain are unlocked by this
      repo (honesty rule satisfied - the commits exist).

## Next in the loop (forge)

- [ ] Operational validation of `merit ingest-mail` against the real mailbox
      (after PR #8 merge + app password).
- [ ] `forge task 7` - job-alert emails to triage queue (`merit queue`,
      deterministic hot/cold prefilter). Issue #7 is open and `agent:ready`;
      best run after real alert emails exist to validate fixture realism.
- [ ] IMAP hardening follow-ups from PR #8 (one scoped issue):
  - `select()`/`search()` return status unchecked - a wrong/missing label
    degrades silently to "0 ingested" instead of a named error.
  - IMAP connection not closed when `login()` fails.
  - `search(None, "ALL")` has no documented ceiling (rescans the whole label
    every run).

## Polish batch (small issues, open on demand)

- [ ] Narrative writer ignores the plain-hyphen rule: strip em/en dashes
      deterministically in the narrative node (post-processing, not prompt
      pleading).
- [ ] Extract fragments compound demands ("cost/latency engineering" becomes
      "cost" + "latency"), producing noisy gap rows in the report. Prompt
      adjustment or heuristic merge.
- [ ] Golden evaluation prints the agreement rate only on failure; log it on
      success too (the number is quotable - README, future benchmark).

## Roadmap

- [ ] **v0.25 - evals:** postings corpus as a LangSmith dataset (owner-side
      LangSmith signup required); LLM-as-judge scoring of report quality
      (GNOMON bridge); prompt iteration against the dataset. Promotes
      LangSmith from partial to strong in the profile.
- [ ] **v0.3 - service:** FastAPI layer mounting the same graph (async
      endpoints, SSE progress), Docker deploy on the existing Coolify VPS.
      The end-to-end showcase.
- [ ] **v1.0 - benchmark:** MERIT's graph vs a custom-loop implementation on
      the same corpus, judged by a GNOMON panel, published through METRON +
      evidence-repo like the GLYPH rounds.

## Standing constraints

- Scraping LinkedIn is permanently out of scope. Ingestion channels are the
  user's own inbox (recruiter-message notifications, job-alert digests) and
  pasted/URL postings. See the spec's v0.2 rationale.
- Personal data (real profile, corpus, inbox files) never enters git; only
  synthetic fixtures are committed.

## Outside this repo (ecosystem)

- [ ] `axon_record_outcome` was not exposed to forge subagent MCP sessions
      (observed on the issue #4 pass); the outcome edge went unrecorded.
      Investigate in the axon repo.
