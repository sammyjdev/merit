# MERIT backlog and next steps

Status snapshot (2026-07-30, wave 2 sealed): phase 1 + operational + hardening/dossier waves done. On master:
six-node graph, CLI (match/resume/rank/queue/track/ingest-mail), security
hardening, CI gate. Golden evaluation passed (agreement >= 80%, 29 postings /
114 pinned verdicts). Live-validated against the owner's real mailbox:
218 InMail postings ingested and ranked (top-15 all AI-engineer roles),
1340 alert digests parsed into a 7024-row triage queue, application ledger
smoke-tested end to end.

## Next in the loop (forge)

- Nothing queued. Issues #14 (hardening) and #15 (dossier) shipped and
  live-validated 2026-07-30: incremental rescan 97s -> 3.3s on unchanged
  mailbox; dossier smoke-tested on a real application (legacy row upgraded,
  jd.md seeded from the ingested posting).

## Awaiting the owner

- [ ] Re-sign the Protocol B unsigned commits at your convenience (7e2151f,
      3d7e54d and the agent/* commits merged via PRs #11-#13).
- [ ] LinkedIn skills update: LangGraph and LangChain (commits exist).
- [ ] New AI-first job alerts are live (old Java-heavy searches replaced
      2026-07-30); let them accumulate - the queue's hot list mirrors alert
      quality, so it improves as the new alerts land.

## Polish batch (small issues, open on demand)

- [ ] Narrative writer ignores the plain-hyphen rule: strip em/en dashes
      deterministically in the narrative node.
- [ ] Extract fragments compound demands ("cost/latency engineering" ->
      "cost" + "latency"), producing noisy gap rows.
- [ ] Golden evaluation prints the agreement rate only on failure; log it on
      success too.
- [ ] `merit queue` ordering: hot list is unordered; reuse rank scoring on
      titles so the hottest entries surface first.

## Roadmap

- [ ] **v0.25 - evals:** postings corpus as a LangSmith dataset (owner-side
      signup); LLM-as-judge scoring of report quality (GNOMON bridge).
      Promotes LangSmith from partial to strong in the profile.
- [ ] **v0.3 - service:** FastAPI layer mounting the same graph, Docker
      deploy on the existing Coolify VPS.
- [ ] **v1.0 - benchmark:** MERIT's graph vs a custom-loop implementation,
      GNOMON panel, published through METRON + evidence-repo.

## Standing constraints

- Scraping LinkedIn is permanently out of scope. Ingestion channels are the
  owner's own inbox (InMail label for recruiter messages, "Linkedin Jobs"
  label for alert digests) and pasted/URL postings. Fetching alert URLs is
  scraping - the queue stores title/company/link only.
- Personal data (real profile, corpus/, inbox files, ~/.merit) never enters
  git; only synthetic fixtures are committed.

## Outside this repo (ecosystem)

- [ ] Forge lanes stop when waiting on background children (observed 4x on
      2026-07-29); needs a synchronous-polling rule in the lane machinery.
- [ ] quench.mutator fabricated a KILLED verdict under sandbox EPERM
      (claude-skills#17); plan stage leaked personal-data paths into plan
      text (claude-skills#18).
- [ ] `axon_record_outcome` not exposed to forge subagent MCP sessions.
