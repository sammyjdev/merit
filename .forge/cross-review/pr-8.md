# Cross-review request: PR #8

- repo: sammyjdev/merit
- pr: https://github.com/sammyjdev/merit/pull/8
- issue: #6 - Mail ingestion: recruiter-message emails feed the full pipeline (v0.2 tracer)
- tier: Legendary
- risk areas hit: personal-data (profile.yaml, corpus, recruiter, LANGSMITH_HIDE), secrets (gitleaks, credential, api key, .env, LANGSMITH_API_KEY)
- gate: 76 passed, 1 deselected; ruff check merit tests clean
- reviewers already run: claude-opus-5@low (spec) APPROVE, codex/gpt-5.6-sol@high (code-quality) APPROVE
- quench: mandatory battery 4/4 killed (EMPTY_RETURN, IDENTITY_RETURN, NEGATE_CONDITIONAL, DROP_SIDE_EFFECT); tier-scaled extras 5/5 killed, 0 survived

## What the maker was asked to do

End-to-end thin slice of the compliant ingestion channel: LinkedIn recruiter-message
notification emails (which carry the message text) land in the user's inbox, MERIT
consumes them over IMAP, and each becomes a posting file ready for `merit match`.
Scraping LinkedIn stays explicitly out of scope.

New module `merit/mail.py` + CLI command `merit ingest-mail`:
1. IMAP fetch (stdlib `imaplib`/`email`, no new deps): `MERIT_IMAP_HOST` (default
   `imap.gmail.com`), `MERIT_IMAP_USER`, `MERIT_IMAP_PASSWORD` (app password,
   env-only, never logged), `MERIT_IMAP_MAILBOX` (default `merit`).
2. Parse: prefer text/plain, fall back to text/html via existing `html_to_text`.
   Detect recruiter-message notifications by sender domain (`linkedin.com`) AND
   subject shape. Non-matching messages skipped and logged, never deleted.
3. Write: `corpus/inbox/<date>-<slug>.md` with a from/subject/date/Message-ID
   header. Dedupe by Message-ID via a local `.seen` ledger.
4. Idempotent and read-only on the mailbox: never delete or move mail.

Acceptance: `pytest -q` green offline, `ruff check merit tests` clean (S ruleset:
credentials never logged or echoed). Live-mailbox validation is explicitly
deferred to post-merge, owner-side.

## What to look for

Findings the same-family (Anthropic) reviewers would be least likely to catch.
Do not re-litigate style or re-run the gate - both already passed. Prefer:
correctness under inputs the tests do not generate, security consequences of the
chosen approach (credential handling around `imaplib`, the read-only mailbox
design via `EXAMINE`/`BODY.PEEK[]` instead of the issue's own "mark as seen"
proposal, the local `.seen`-ledger dedupe/crash-recovery design), and assumptions
the diff makes about the environment (IMAP server behavior, Gmail-specific label
semantics, encoding edge cases in `email.message_from_bytes`).

Already-known non-blocking follow-ups (no need to re-report these): `select()`/
`search()` IMAP status codes are not checked (a missing/misspelled mailbox label
degrades to a silent "0 ingested"); the `IMAP4_SSL` connection is not closed if
`login()` raises; `search(None, "ALL")` has no documented ceiling (re-downloads
the full label every run).
