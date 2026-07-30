# Code-quality review - job-alert triage queue (v0.2)

Reviewer: `legendary.review.quality` (independent code-quality reviewer, read-only).
Scope: working diff on `agent/issue-7` (`merit/queue.py` new; `merit/mail.py`,
`merit/cli.py`, `merit/profile.py`, `tests/test_mail.py`, `tests/test_profile.py`
modified; `tests/test_queue.py`, `tests/test_cli_queue.py`,
`tests/fixtures/mail/job_alert.eml` new).

Verdict: BLOCK

## Environment limitation (disclosed, not a finding)

`Bash` was unavailable for the whole review (`EPERM: operation not permitted,
mkdir '/Users/samdev/.claude/session-env/...'`), and no `Grep`/`Glob` tool is
exposed in this session. Consequences, stated plainly:

- I could **not** run `git diff master...HEAD`. The structural test-file check was
  performed by reading the current test files and reasoning about additivity, not
  from a diff.
- I could **not** run `pytest -q` or `ruff check merit tests`. No claim below
  rests on a suite run; every finding is derived from reading the code.
- I could not locate/read `RULES.md` or `craft-lessons.md` (no glob), so the
  risk-area invariant check is unverified rather than passed.

## Structural check: existing test files

`git status` shows `tests/test_mail.py` and `tests/test_profile.py` as modified -
the rubric's literal reading makes any existing-test modification an immediate
BLOCK. Reading both files, the changes appear **purely additive**: every added
test exercises only symbols introduced by this branch (`strong_terms`,
`is_job_alert`, `message_html`, `message_date`, `ingest_alerts`), and the
pre-existing tests read coherently and still assert the old contracts
(`test_connect_selects_readonly`, `test_fetch_messages_uses_peek_not_rfc822`,
the `.seen` identity test, etc.). I therefore do **not** block on this line
item - but because I could not produce the diff, this is an assessment, not a
verification. If the loop's gate can run `git diff master...HEAD -- tests/`, it
should confirm no pre-existing assertion was weakened before this review is
treated as settled.

New tests do target observable behavior (parsed entries, hot/cold split, queue
file contents, CLI output) rather than internals, and would genuinely fail
without the implementation - `merit/queue.py` does not exist on `master`.

## Blocking finding

### B1. `connect()` never quotes a mailbox name containing spaces - `merit ingest-mail` cannot select the one mailbox this feature exists for

`merit/mail.py:67`

```python
conn.select(mailbox, readonly=True)
```

`imaplib.IMAP4.select` passes the name straight into `_simple_command('SELECT',
mailbox)`, which joins arguments with a single space and applies **no** quoting.
With the documented real value `MERIT_IMAP_MAILBOX="Linkedin Jobs"` the wire
command becomes `SELECT Linkedin Jobs`, which the server rejects.

This is not speculation on my part - the issue states it as an operational fact:

> Gmail label: `Linkedin Jobs` (note the space - `MERIT_IMAP_MAILBOX` value must
> be quoted in IMAP `SELECT`, i.e. `conn.select('"Linkedin Jobs"')`; bare
> `select('Linkedin Jobs')` fails).

Failure scenario: user exports `MERIT_IMAP_MAILBOX="Linkedin Jobs"`, runs
`merit ingest-mail`, and gets an `imaplib.IMAP4.error` traceback out of
`connect()` (which is outside the `MailError` handling in `cli.py:92-96`, so it
is an unhandled traceback, not a friendly message). Zero alerts are ever
ingested. The entire queue feature is unreachable on the real mailbox; it only
works in the fixture tests.

Why this is blocking rather than a note: the branch's whole purpose is ingesting
the `Linkedin Jobs` digest, the issue names the exact defect and the exact fix,
and the delivered code does not honor it. The acceptance list (offline `pytest`,
`ruff`, `merit queue` over a fixture-built queue) simply does not exercise the
path, so a green suite is not evidence here.

Fix shape, and note it does **not** require touching the existing
`test_connect_selects_readonly` assertion (which passes `"custom-box"`, no
space): quote only when needed, e.g. wrap the name in `"` when it contains a
space or is not already quoted, then add a new test for the spaced value. An
`imaplib.IMAP4.error` around `select` should also be converted to `MailError` so
`cli.py` renders it instead of a traceback.

## Non-blocking findings (fix while B1 is in hand)

### N1. `url` bypasses the sanitizer the module deliberately introduced

`merit/queue.py:27-28,47-51`; rendered at `merit/cli.py:131,135`

`_sanitize` exists precisely because email content is attacker-controlled and
lands on a terminal - `title` and `company` are both stripped of
`[\x00-\x1f\x7f]`, and `test_parse_alert_strips_control_characters_from_fields`
locks that in. `href` is taken verbatim from the attacker's HTML and then echoed
by `merit queue` and persisted to `corpus/queue.json`.

Failure scenario: a digest (or a spoofed message that clears the sender check)
carries `href="https://www.linkedin.com/jobs/view/1/?x=\x1b[2J\x1b[1;1H"`. The
`https://` + `/jobs/view/` guard passes, and `merit queue` emits raw ANSI that
clears the user's screen and repositions the cursor - hiding or forging
surrounding queue rows. Same class of problem the title sanitizer already
defends against; the inconsistency is the bug. Apply `_sanitize` to the href (and
add the url case to the control-char test).

### N2. `load_entries` turns any malformed `corpus/queue.json` into a traceback, and the test that looks like it covers this does not

`merit/queue.py:90-94`; `tests/test_cli_queue.py:77-87`

`json.loads` and `Entry(**row)` are both unguarded: a zero-byte file raises
`json.JSONDecodeError`, and a row carrying an unknown key (a field added by a
later version, a hand-edit) raises `TypeError`. `merit queue` has a friendly
branch only for the *missing*-file case, so both surface as tracebacks.

The gap is masked by naming: `test_queue_empty_file_is_friendly_not_a_traceback`
points at `tmp_path / "missing-queue.json"`, i.e. it exercises the
`path.exists()` early return, not an empty file. The test name asserts coverage
the test does not provide - rename it, and add a real empty-file/garbage-file
case (or make `load_entries` tolerant with a clear error).

Mitigating: writes are atomic (`tmp` + `chmod 0o600` + `replace`,
`merit/queue.py:120-124` - good, and correctly mirrors the `ingest_messages`
precedent), so self-inflicted corruption is unlikely. Hand-editing and version
skew are not.

### N3. The two ingest passes cross-skip every message, producing ~1.5k stderr lines per run at documented scale

`merit/cli.py:101-109`

`ingest_messages` and `ingest_alerts` each iterate the **same** `raws` and each
append a skip reason for everything the other one owns. Per the issue's own
field data (1340 job alerts, 218 InMails in the real mailbox), a single
`merit ingest-mail` prints roughly 1340 `skipped (not a job alert)` lines plus
218 `skipped (not a recruiter message)` lines - burying the handful of genuine
skips (`no text body`, `unparseable message`) that the operator actually needs to
see. The skip channel stops being useful exactly at the scale it matters.

Cheapest fix consistent with the current shape: classify once in `cli.py` and
hand each pass only its own raws, so a message routed to the other adapter is
not reported as a skip at all.

### N4. `Entry.location` is a permanently-`None` field with a test that pins the emptiness

`merit/queue.py:24`; `tests/test_queue.py:77-79`

The comment is honest and the reasoning is right (digests carry no location - the
issue's real-world note confirms it, and inventing one would be dishonest
output). But the result is a field that is written to every JSON row, asserted to
be always `None`, and read by nothing. The design note's `location` implication
is validly exempted by the field data; the field itself is then dead surface.
Either drop it, or keep it with the exemption recorded in the spec rather than
only in a code comment.

## What is right (so a fix round does not regress it)

- `queue.py` is stdlib-only and imports nothing from `merit.*`, enforced by an
  AST test rather than a comment - a real invariant, cheaply held.
- Prefilter is genuinely deterministic: `is_hot` is a pure substring test over
  `strong_terms`, no LLM, no network. `strong_terms` correctly derives aliases
  from `strong`-status skills only, and `test_strong_terms_excludes_non_strong...`
  pins the `pytorch`-is-a-gap case.
- `dedupe_key` drops the query string, so LinkedIn's per-send `trackingId`/`refId`
  cannot defeat dedupe - the non-obvious part of "dedupe by url", and it is
  tested directly.
- `href.startswith("https://")` blocks the `javascript:` shape, with a test.
- `is_job_alert` reuses the `RECRUITER_SENDERS` precedent from 3d7e54d
  (exact-sender OR domain+subject), keeps the `.linkedin.com` suffix check that
  rejects `evil-linkedin.com`, and mutual exclusivity with
  `is_recruiter_message` is asserted both ways.
- No scraping: nothing fetches the alert URLs. Out-of-scope boundary respected.
- The honest-limitation line (`merit match -`) is printed and tested.

## Summary

The core design is sound, lean, and the dedupe/determinism/no-scraping
constraints are all honored. It is blocked on B1: `connect()` cannot select the
mailbox the issue documents as the source, so the delivered feature works on the
fixture and not on the user's account, and the failure arrives as an unhandled
traceback. Fix B1 (plus N1-N3, all small and local), re-run
`pytest -q` / `ruff check merit tests`, and this is close to approvable.

Verdict: BLOCK
