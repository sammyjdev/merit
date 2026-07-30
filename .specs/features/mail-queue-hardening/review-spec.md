# Spec review - mail/queue hardening (issue #14)

Reviewer: independent spec reviewer (Sonnet 5), tier Legendary.
Scope: `master...HEAD` (working tree: `merit/cli.py`, `merit/mail.py`, `merit/queue.py`
modified; `tests/test_mail_status.py`, `tests/test_mail_cursor.py`,
`tests/test_queue_normalize.py` new).

Verdict: APPROVE

## Evidence limitation (stated up front)

The `Bash` tool failed with `EPERM: operation not permitted, mkdir
'/Users/samdev/.claude/session-env/...'` on every invocation, in this session and
in a delegated subagent. Consequently I could **not** run `git diff`, `pytest`, or
`ruff`. The review below is a full manual read of the changed modules plus a
hand-trace of every pre-existing test in `tests/test_mail.py` and
`tests/test_queue.py` against the new code. The gate stage must still produce a
real green `ruff + pytest` run before merge - this review does not substitute for
it.

## Structural check: existing test files

The git status snapshot for this branch lists exactly three modified tracked
files, all under `merit/`, and three untracked new test files. **No existing test
file was modified.** The executor's anti-modification rule is honored. Passes the
pre-semantic gate.

## Criterion-by-criterion

**1. Named errors for select/search failures.**
`MailError` gains `SelectError` and `SearchError` subclasses (`mail.py:38-43`).
`_ok()` (`mail.py:53-61`) raises the caller-chosen subclass when `typ != "OK"` or
when `data` is malformed. The malformed-data predicate is the correct one: it
rejects `None`, `[None]`, `[]` but deliberately accepts `[b""]`, which is the
legitimate empty-mailbox response - and there is a test locking exactly that
distinction (`test_search_ok_truly_empty_mailbox_returns_no_messages_and_fetches_nothing`
vs `test_search_ok_with_malformed_data_raises_search_error_not_zero_messages`).
That second test names the 2026-07-29 masking bug and is the one that matters:
without `_ok`, `data[0]` would be `None`, `nums` would be `[]`, and the run would
report "zero messages" instead of failing. Asserting tests present for SELECT
(status and malformed shape), SEARCH, FETCH, and for the subclass-is-a-`MailError`
relation. Criterion met.

**2. Login failure closes the socket.**
`connect()` (`mail.py:88-101`) sets a flag inside the `except`, then raises
*outside* it after `_close_quietly(conn)`. Tested by
`test_login_failure_closes_the_socket`. The out-of-except raise is not
incidental: `test_login_failure_preserves_context_invariant` asserts both
`__cause__` and `__context__` are `None`, which `raise ... from None` inside the
except block would not give (it suppresses display, not `__context__`). That
invariant was already asserted by the frozen `test_connect_login_failure_never_leaks_password`,
and the refactor preserves it. `_close_quietly` swallows exceptions from `logout()`
itself, covered by `test_login_failure_with_logout_itself_raising_still_raises_mail_error`.
SELECT failure closes the socket too (`mail.py:110-112`), which the issue did not
ask for but is the same defect class and is tested. Criterion met.

**3. Bounded rescan via UID cursor, with `--full`.**
`_fetch_messages_cursor` (`mail.py:135-177`) is correct on the points that
actually bite:
- UIDVALIDITY is read via `conn.response()` *before* any other command, with an
  accurate comment about the buffer being popped. A server that omits it yields
  `""`, handled.
- The cursor record carries a full identity (host/user/mailbox/uidvalidity).
  A mismatch, a missing file, corrupt JSON, or a non-dict payload all degrade to
  a full `UID SEARCH ALL`, never to "skip everything". Six tests cover those
  branches individually.
- The client-side `u > last_uid` filter (`mail.py:162`) is the non-obvious
  correctness point: IMAP `n:*` returns the highest UID even when `n` exceeds every
  UID present. Without that filter the "unchanged mailbox" case would refetch the
  newest body every run and the acceptance criterion would silently fail.
  `test_second_run_unchanged_mailbox_fetches_nothing` asserts zero FETCH calls
  against a fake that returns exactly that boundary UID. This is the criterion's
  proof and it is a real one.
- The cursor is monotonic (`mail.py:174`) - a transient empty search cannot
  regress on-disk state.
- Cursor write is atomic (tmp + `replace`) and `0o600`, tested.

`--full` (`cli.py:119-120`) unlinks the cursor and is tested end-to-end
(`test_cli_full_flag_refetches_everything_and_rewrites_cursor`), as is cursor
placement inside `--out-dir`.

Backward compatibility is handled deliberately: `fetch_messages` dispatches on
`getattr(conn, "merit_cursor", None)` (`mail.py:181`) and falls through to the
original `search(None, "ALL")` path otherwise. This is load-bearing for a frozen
test - `test_fetch_messages_issues_no_mutating_calls` asserts no call named `uid`
is ever issued, and its `_FakeConn` has no `merit_cursor` attribute. The fallback
keeps that test green rather than requiring it to be edited. Explicitly re-locked
by the new `test_bare_fetch_messages_without_cursor_attrs_behaves_like_before`.
Criterion met.

**4. Normalized queue URLs + migration.**
`normalize_url` (`queue.py:91-102`) collapses `/comm/` prefix, tracking params,
and trailing-slash variance to `<scheme>://<netloc>/jobs/view/<id>/`. Applied at
persistence time in `append_entries`, not in `parse_alert` - which is why the
frozen `test_parse_alert_extracts_three_entries_with_correct_fields` (asserting
raw tracking URLs off the parser) still passes. Correct placement.

Migration (`queue.py:117-135`) normalizes and dedupes pre-existing rows on the
same pass, first-occurrence-wins, and rewrites the file even when zero new
entries arrive (`existing_changed`). The `not added and not existing_changed`
early return keeps the second call a genuine no-op, asserted via `st_mtime_ns`.
Frozen-test compatibility traced: `test_append_entries_dedupes_within_batch_by_url`
still holds (`load_entries(path) == added`, since `normalized_existing` is empty),
and `test_append_entries_returns_only_new_entries` / `..._preserves_insertion_order`
use `x.example/jobs/view/N/` URLs that normalize to themselves. Criterion met.

## Nothing extra

The diff is confined to the four issue items. No speculative abstraction, no
adjacent refactoring. The two `MailError` subclasses, `_ok`, and `_close_quietly`
are each used more than once. `dedupe_key` was rewritten to compose over
`normalize_url` rather than duplicate the parsing.

## Non-blocking observations

1. **Cursor advances before ingestion is persisted** (`cli.py:125-132`). The
   cursor file is written inside `fetch_messages`, before `ingest_messages` /
   `ingest_alerts` run. A crash between the two loses those messages permanently
   for the incremental path. Partly mitigated: recruiter messages are re-guarded
   by `.seen` and queue rows by URL dedupe, so a *re-run with `--full`* recovers
   cleanly. Worth a line in the command's docs rather than a code change.
2. **Non-int `uid` in an otherwise well-formed cursor** crashes with a bare
   `TypeError` (`mail.py:156`, `last_uid + 1`), not a `MailError`. `_read_cursor`
   advertises tolerance for corruption but only validates the outer JSON shape,
   not the `uid` type. Reachable only by hand-editing `.last-uid`; low value to
   fix, but the docstring slightly over-promises.
3. **`conn.logout()` in the CLI `finally` is unguarded** (`cli.py:130`). On a
   genuinely broken socket, `logout()` can raise and would replace the intended
   `exit 1` with a traceback, masking the real `MailError`. `_close_quietly`
   already exists for exactly this; using it here would be consistent.
4. **`normalize_url` preserves netloc rather than forcing `www.linkedin.com`**, a
   conscious deviation from the issue's literal target string, documented in the
   docstring and locked by `test_normalize_url_preserves_scheme_and_netloc_not_rewritten_to_linkedin`.
   Equivalent in practice (real digest hrefs are all `www.linkedin.com/comm/...`)
   and safer for non-LinkedIn hosts. Consequence to note: URLs differing only by
   host variant (`linkedin.com` vs `br.linkedin.com`) will not dedupe against each
   other. No production data exhibits this today.
5. Cursor file placement inside `--out-dir` is safe against the sibling consumers
   I checked: `rank_dir` globs `*.md` (`rank.py:75`) and the `.seen` precedent
   already establishes dotfiles in that directory.

## Test quality

New tests assert observable behavior - raised exception types, exception message
contents, files written and their permissions, and the sequence of IMAP wire
commands issued. Inspecting `fake.calls` is legitimate here: the IMAP command
sequence *is* the contract under test (the whole point of criterion 3 is "issues
no FETCH"), not an implementation detail. Every new test would fail against the
pre-change code: `SelectError`/`SearchError` do not exist, cursor mode does not
exist, `normalize_url` does not exist.

Verdict: APPROVE
