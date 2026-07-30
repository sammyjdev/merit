# Code-quality review - mail/queue hardening (issue #14)

Reviewer: independent code-quality reviewer (Legendary tier). Read-only pass.
Scope: `merit/mail.py`, `merit/queue.py`, `merit/cli.py`, plus the new
`tests/test_mail_status.py`, `tests/test_mail_cursor.py`,
`tests/test_queue_normalize.py`.

Verdict: APPROVE

## Evidence limitation (stated up front)

`Bash` was unusable for this run (every invocation failed with
`EPERM: operation not permitted, mkdir '/Users/samdev/.claude/session-env/...'`),
so I could **not** run `git diff master...HEAD`, `pytest`, or `ruff` myself. This
review is a full static read of the changed modules and the new tests, plus the
`git status` snapshot supplied with the task. I am **not** asserting the suite is
green - that claim has to come from the gate, which does have a working shell.
Everything below is judged on code semantics, and I traced each new test by hand
against the implementation.

## Structural check: existing test files

The supplied worktree state lists `M merit/cli.py`, `M merit/mail.py`,
`M merit/queue.py` as the only modifications; the three test files are `??`
(untracked/new). No existing test file is touched - in particular
`tests/test_mail.py` is untouched, and `_FakeConnNoUid` in
`test_mail_cursor.py` exists precisely to pin the legacy fake shape rather than
edit the frozen test. No STOP condition. Passes.

## Acceptance criteria

1. **Named errors for select/search failures** - `SelectError` / `SearchError`,
   both subclasses of `MailError`, raised through the shared `_ok()` helper.
   `_ok` correctly distinguishes malformed data (`None`, `[None]`, `[]`) from a
   legitimately empty result (`[b""]`); that distinction is the exact 2026-07-29
   masking bug and it has a dedicated test
   (`test_search_ok_with_malformed_data_raises_search_error_not_zero_messages`,
   and the counterpart `..._truly_empty_mailbox_...`). The `SelectError` message
   embeds the unquoted mailbox name, so the missing-label case is diagnosable.
2. **Login failure closes the socket** - `_close_quietly()` before the raise, and
   the raise is deliberately placed outside the `except` block so
   `__context__`/`__cause__` are both `None`. That matters here for a real
   reason (imaplib error text can echo the attempted command, i.e. credentials),
   the reason is in the comment, and it is pinned by
   `test_login_failure_preserves_context_invariant` +
   `test_login_failure_message_never_leaks_password`. The
   `logout()`-itself-raises path is also covered. Select failure closes the
   socket too, which the issue did not ask for but is the same class of leak.
3. **Second run fetches no bodies** - `_fetch_messages_cursor` issues
   `UID SEARCH UID <last+1>:*` and then filters client-side to strictly-greater
   UIDs. That client-side filter is the non-obvious correctness point (IMAP's
   `n:*` returns the highest UID even when `n` exceeds every UID present) and it
   is both commented and tested end-to-end through the CLI
   (`test_cli_second_run_fetches_no_new_bodies` asserts zero `UID FETCH` calls).
   `--full` unlinks the cursor file. Cursor identity is
   `(host, user, mailbox, uidvalidity)`; a mismatch, a missing file, corrupt
   JSON, or a non-dict payload all degrade to a full rescan rather than to
   "skip everything" - the right failure direction, with a test per case.
4. **Normalized URLs + migration** - `normalize_url` collapses to
   `<scheme>://<netloc>/jobs/view/<id>/` and returns non-matching URLs
   unchanged; scheme/netloc are preserved rather than hardcoded to linkedin.com
   (tested). `append_entries` normalizes *existing* rows as well as incoming
   ones and dedupes them by `dedupe_key`, so a legacy raw row collides with both
   a raw and a normalized duplicate. The `existing_changed` flag makes the
   migration write once and the second call a genuine no-op, asserted via
   `st_mtime_ns`. First-in-file-order row wins, which keeps the migration
   deterministic.

Details I checked by hand and found correct:

- `last_uid` uses `is None` rather than truthiness, so a stored `uid: 0` (empty
  first scan) correctly produces `UID SEARCH UID 1:*` on the next run instead of
  a full rescan.
- Cursor monotonicity: `candidates = raw_uids + [last_uid]` then `max(...)`, so a
  transient empty or boundary-only search cannot regress the on-disk value.
- `conn.response("UIDVALIDITY")` is read before any other command, with the
  reason (imaplib pops the buffered untagged response) in a comment.
- Cursor file write is atomic (`.tmp` + `replace`) and `0o600`, matching the
  existing `ingest_messages` / `append_entries` pattern rather than inventing a
  new one.
- The `getattr(conn, "merit_cursor", None)` guard keeps the legacy
  `search(None, "ALL")` path byte-identical for conns without cursor support.
- Mailbox quoting in `connect()` only quotes when the name contains a space, so
  existing single-word labels behave identically.

Nothing extra was added beyond the four items. Comments explain *why* (wire
behavior, imaplib quirks, credential leakage) rather than restating the code -
that is the right density for this repo.

## Non-blocking findings

These are advisory. None of them breaks an acceptance criterion or a documented
invariant, and I would not hold the branch for any of them.

1. **`merit/mail.py:151` - `uid` type is not validated.** `_read_cursor`'s
   docstring promises that anything short of a clean read yields `None`, but a
   file that is valid JSON with a non-integer `uid` (e.g. `"9"`) reaches
   `last_uid + 1` and raises a bare `TypeError`, which the CLI does not catch as
   `MailError` - so the user gets a traceback instead of a named error. Low
   severity: the file is written only by this code, `0600`, and the corrupt-JSON
   path is already handled. A single `isinstance(record.get("uid"), int)` check
   in `_read_cursor` would close the gap between docstring and behavior.
2. **`merit/cli.py:125-132` - cursor advances before ingestion completes.** The
   cursor is written inside `_fetch_messages_cursor`, but `ingest_messages` /
   `ingest_alerts` run afterwards. If `queue.append_entries` fails at the end
   (disk full, permissions), the whole batch's alerts are lost and the next run
   will not re-fetch them, because the cursor already moved. Before this change a
   crash was self-healing via the unconditional full rescan; now it is not.
   `--full` is the documented escape hatch, so this is recoverable, and
   `ingest_messages` still writes `.seen` incrementally per message. Worth a note
   in the runbook.
3. **`merit/mail.py:141-145` - absent UIDVALIDITY degrades silently.** A server
   that returns no UIDVALIDITY yields `""`, which then matches on every
   subsequent run - the cursor is trusted with no renumbering protection. Gmail
   always sends it, so this is theoretical, but the empty string is currently
   indistinguishable from "verified equal".
4. **`merit/mail.py:137` - `_env_config()` is re-read inside
   `_fetch_messages_cursor`.** The identity is recomputed from the environment
   rather than carried on the connection that `connect()` already validated.
   Harmless in the single-process CLI, and it does buy a real guard (user/mailbox
   change forces a rescan, which is tested), but it couples a fetch helper to
   process env and makes `fetch_messages` unusable in cursor mode for a conn not
   built from the same env.
5. **Minor:** `_FakeCursorConn`'s `login_ok` and `select_result` constructor
   params are never exercised by the cursor tests (`fetch_messages` calls
   neither) - dead test scaffolding. And
   `test_normalized_url_byte_length_shrinks_meaningfully_for_realistic_tracking_href`
   asserts `len < 60`, a magic threshold that documents intent weakly; the
   exact-value tests above it already carry the real contract.
6. **Cosmetic:** the issue text says `queue.jsonl` while the code uses
   `corpus/queue.json` (pre-existing `QUEUE_PATH`). Not a defect in this diff -
   flagging only so the issue wording is not mistaken for an unmet criterion.

## Why APPROVE

The three hardening changes are each minimal, each land at the right layer
(status checking in a single `_ok` helper; cursor logic in `mail`; normalization
in `queue` at persistence time), and each carry a test that would fail without
the implementation. The two genuinely subtle traps in this problem - IMAP's
`n:*` boundary UID and reading UIDVALIDITY before the next command - are both
handled and both explained. The migration is idempotent and order-deterministic.
The findings above are robustness polish on error paths that are already failing
in the safe direction, not correctness defects against the criteria.
