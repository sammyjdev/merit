# Review — job-alert triage queue (issue #7), tier Legendary

Reviewer: independent spec reviewer (did not write the code).
Scope: `master...HEAD` working tree of `agent/issue-7`.

Verdict: APPROVE

## Environment limitation (stated up front, affects confidence not the verdict)

`Bash` was unavailable for the whole review (`EPERM: mkdir /Users/samdev/.claude/session-env/...`),
on every attempt including with the sandbox override. Consequences:

- I could **not** run `pytest -q` or `ruff check merit tests`. The acceptance criterion
  "suite green offline / ruff clean" is **unverified by this review** and must be
  confirmed by the Gate, which runs both anyway.
- I could **not** run `git diff master...HEAD`, so the structural test-file check was
  done by reading the files instead of by diffing them (see below).

Everything else below is from direct reading of the source.

## Structural check: modifications to existing test files

Working tree shows `tests/test_mail.py` and `tests/test_profile.py` as modified.
Read in full, both changes are **additive**:

- `tests/test_mail.py`: one new module constant (`JOB_ALERT_DIGEST_RAW`) plus four new
  sections appended after the pre-existing ones — `is_job_alert()`, `message_html()`,
  `message_date()`, `ingest_alerts()`. Every pre-existing test (connect/fetch_messages/
  is_recruiter_message/message_text/slug/ingest_messages, including the `3d7e54d`
  InMail-sender tests) is present with its assertions intact — nothing weakened,
  renamed, or relaxed. Notably `test_job_alert_shaped_subject_is_rejected` still
  asserts the recruiter check rejects alert-shaped subjects, and the new
  `test_recruiter_and_alert_checks_are_mutually_exclusive` pins both directions.
- `tests/test_profile.py`: one new import (`profile as profile_mod`) and two new
  tests for `strong_terms`. The six pre-existing tests are unchanged.

Adding new tests to an existing file is permitted (RED phase); the STOP rule targets
altering existing tests, and I found no evidence of that. Caveat: without `git diff`
I am asserting this from content shape, not from a byte-level comparison.

## Criteria coverage (issue #7)

| Criterion | Implementation | Asserting test |
|---|---|---|
| Detect job-alert emails in the same `ingest-mail` pass | `mail.is_job_alert` (`JOB_ALERT_SENDERS` = `jobalerts-noreply@linkedin.com` mirroring the `RECRUITER_SENDERS` precedent from `3d7e54d`, plus domain+subject-marker fallback); `cli.ingest_mail` calls `ingest_alerts` alongside `ingest_messages` | `test_job_alert_digest_fixture_is_detected`, `test_job_alert_sender_on_lookalike_domain_is_rejected`, `test_ingest_mail_also_queues_job_alerts` |
| Parse to `{title, company, location, url, alert_date}` from the html body, no new deps | `queue._AlertParser` on stdlib `html.parser`; `merit/queue.py` imports stdlib only | `test_parse_alert_extracts_three_entries_with_correct_fields`, `test_parse_alert_ignores_non_job_anchors`, `test_message_html_returns_html_part_not_plain` |
| Deterministic keyword prefilter, hot/cold, no LLM calls | `queue.is_hot` + `profile.strong_terms` (strong skill names + their aliases, lowercased substring) | `test_prefilter_split_matches_fixture_profile`, `test_is_hot_*`, `test_queue_module_imports_no_llm_layer` (AST-level proof of no `merit.*` import) |
| Store in `corpus/queue.json`, append, dedupe by url | `queue.append_entries` with `dedupe_key` (scheme+netloc+path, tracking params dropped), atomic tmp+replace, mode 0600 | `test_append_entries_dedupes_within_batch_by_url`, `test_append_entries_dedupes_against_existing_file`, `test_dedupe_key_ignores_tracking_query_params`, `test_ingest_alerts_second_run_adds_nothing`, `test_queue_write_is_atomic_and_leaves_no_tmp_file` |
| `merit queue`, hot first, `--all` includes cold | `cli.queue_cmd` | `test_queue_lists_hot_entries_first`, `test_queue_hides_cold_entries_by_default`, `test_queue_all_flag_includes_cold_entries` |
| Honest limitation printed | trailing `Full match requires pasting the description: merit match -` | `test_queue_prints_honest_limitation_with_match_stdin_hint` |
| Fixture: 3 postings, one strong-alias match, one no match, one duplicate url | `tests/fixtures/mail/job_alert.eml` — real subject shape with curly quotes, `/comm/jobs/view/` links, two decoy anchors (See all / Unsubscribe) | consumed by the parser and prefilter tests above |

Prefilter split checks out against `tests/fixtures/profile_small.yaml`
(`FastAPI` strong + alias `REST APIs`; `PyTorch` is `gap`): entry 0 hot, entry 1 cold,
entry 2 (the duplicate) hot. `strong_terms` correctly excludes non-strong aliases —
pinned by `test_strong_terms_excludes_non_strong_skills_and_their_aliases`.

Out-of-scope respected: no URL fetching anywhere in `queue.py`/`ingest_alerts`, and
no ranking beyond the boolean prefilter. Nothing extra shipped: the added surface
(`message_html`, `message_date`, `strong_terms`, `--queue-path`) is all load-bearing
for the criteria or for offline testability. `Entry.location` is always `None`,
which is honest about the digest's real content and is documented plus pinned by
`test_parse_alert_location_is_always_none`.

Tests target observable behavior (parsed entries, file contents, CLI output, file
mode) rather than internals, and would fail without the implementation —
`merit/queue.py`, `is_job_alert`, `ingest_alerts`, `strong_terms` and the `queue`
command are all new, so every new test is genuinely RED before the change.

## Non-blocking findings

1. **`corpus/queue.json` has no `.seen`-style guard, only url dedupe — by design, but
   the whole 1340-message mailbox is re-parsed on every run.** `cli.ingest_mail`
   feeds the same `raws` to both `ingest_messages` and `ingest_alerts`, and each
   emits one stderr skip line per message it does not own, so a real run prints
   ~2× the mailbox size in skip noise. Correctness is fine (dedupe holds); this is
   output hygiene. Consider filtering by classifier before the two passes, or
   dropping the per-message skip line for the "belongs to the other adapter" case.

2. **`queue._sanitize` deletes `\n`/`\t` without substituting a space.**
   `[\x00-\x1f\x7f]` includes newline, so a title whose HTML wraps directly between
   two word characters becomes glued (`Senior Backend\nEngineer` → `Senior
   BackendEngineer`), which then silently misses the substring prefilter. In practice
   email HTML indentation leaves a surrounding space and quoted-printable soft breaks
   are decoded away, so this is unlikely rather than impossible. One-line hardening:
   collapse whitespace after stripping controls (`re.sub(r"\s+", " ", ...)`).

3. **The company heuristic is fixture-shaped and unvalidated against a real digest.**
   `_AlertParser` takes the first non-empty text chunk after an eligible `</a>` as the
   company. The synthetic fixture places `<p>Company</p>` right after the title anchor;
   the real subject shape is `Company - Job title`, so a digest that renders the
   company *before* the anchor yields `company=None` (degraded, not crashing —
   `queue_cmd` prints `unknown company`). Unlike `3d7e54d`, which was grounded in a
   20/20 operational sample, no real `.eml` backs this layout. Worth one real-sample
   check before trusting the company column.

4. **`MERIT_IMAP_MAILBOX` with a space still is not quoted for `SELECT`.** The issue's
   real-world facts call this out explicitly: the alerts live under the Gmail label
   `Linkedin Jobs`, and `imaplib.IMAP4.select` passes the mailbox through unquoted, so
   `SELECT Linkedin Jobs` is two arguments and fails. `mail.connect` (pre-existing,
   from the recruiter issue) passes `mailbox` bare. Not blocking: it is outside this
   issue's stated acceptance, sits in untouched code, and fixing it here would violate
   the surgical-changes rule — but the queue feature cannot be exercised end to end
   against the real mailbox until it is fixed. Recommend a follow-up issue.

5. **Two new CLI assertions read stderr through `result.output`.**
   `test_ingest_mail_prints_queue_hint_and_count` asserts `"queued 2"` and
   `"merit queue"`, both emitted with `err=True`. On Click ≥ 8.2 `Result.output` is
   stdout only (`mix_stderr` is gone), so these would fail. `typer>=0.12` is unpinned
   in `pyproject.toml` and the pre-existing `tests/test_cli.py` only ever asserts on
   stdout, so this branch is the first place the distinction matters. I could not run
   the suite to settle it — this is the single spot I would expect a red test, and the
   Gate's `pytest -q` decides it. If it fails, the fix is `result.stderr`, not
   moving the hints to stdout.

6. **Substring matching on strong-skill names is a false-positive vector for short
   names.** `is_hot` is plain `term in title.lower()`, so a strong skill named `Go`
   or `R` would mark almost everything hot. The fixture profile has no short names,
   and the issue explicitly specified case-insensitive substring, so this matches the
   spec — flagging it as the known cost of the chosen rule, to revisit if the queue
   gets noisy (which the issue already anticipates as a later issue).

7. **`load_entries` uses `Entry(**row)`**, so a hand-edited or schema-drifted
   `queue.json` with an extra key raises `TypeError` as a raw traceback out of
   `merit queue`. Minor robustness gap; the friendly-empty path is covered
   (`test_queue_empty_file_is_friendly_not_a_traceback`) but the malformed path is not.

## Why APPROVE rather than BLOCK

Every acceptance bullet and design note maps to an asserting test; the module boundary
the project cares about (`merit/queue.py` is stdlib-only, no `merit.*`, no LLM, no
network) is enforced by an AST test rather than by convention; the security posture of
the existing mail layer is carried forward (atomic write, 0600, no body/secret leakage
into skip reasons, lookalike-domain rejection tested for the new sender list); and the
diff adds no speculative surface. The findings above are hygiene, real-world-grounding,
and robustness items — none is a defect in the criteria as specified, and none is worth
a fix round on its own. Findings 4 and 5 are the two that deserve action: 4 as a
follow-up issue, 5 as whatever the Gate's `pytest -q` reports.
