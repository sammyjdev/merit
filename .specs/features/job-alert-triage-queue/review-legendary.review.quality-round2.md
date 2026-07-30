# Code-quality re-review (round 2, fix round) — job-alert-triage-queue

Scope: ONLY the fix round for blocking finding B1 (unquoted IMAP `SELECT`) plus the
non-blocking url-sanitization follow-up. Items explicitly declared out of scope by
the fix-round brief (empty vs malformed queue.json, `Entry.location` dead field,
stderr noise, missing `select()` status check) were not re-litigated.

Verdict: APPROVE

## Tooling limitation (must be read alongside the verdict)

The Bash tool was unusable for the entire review: every invocation, including from a
delegated subagent, failed with

```
EPERM: operation not permitted, mkdir '/Users/samdev/.claude/session-env/d56d041b-e5ac-4d3c-86f9-4fab9109d788'
```

Consequences, stated plainly rather than glossed:

- **(b) test-file diff and (c) the gate were NOT executed by me.** I could not run
  `git diff -U0 -- tests/`, `pytest`, or `ruff`. My verdict rests on static reading
  of the working-tree files, not on a green gate. The Gate stage must supply that
  evidence independently; if the gate is red, this APPROVE is void.
- The structural pre-semantic check ("any modification to an existing test file is an
  immediate BLOCK") could therefore only be evaluated indirectly — see (b) below.

## (a) B1 — is the blocking finding resolved? YES

`merit/mail.py:67-72`:

```python
select_mailbox = f'"{mailbox}"' if " " in mailbox else mailbox
conn.select(select_mailbox, readonly=True)
```

- The real reported case is fixed. `MERIT_IMAP_MAILBOX="Linkedin Jobs"` now emits
  `SELECT "Linkedin Jobs"` — a well-formed IMAP quoted string. `imaplib.IMAP4.select()`
  does no quoting of its own (it concatenates args into the command line), so quoting at
  the call site is the correct layer, and the comment at 67-70 records exactly why.
- Behavior for single-word names is bit-identical to before, so the fix is
  non-regressive on the existing contract.
- `tests/test_mail.py:189-198` (`test_connect_quotes_mailbox_name_containing_a_space`)
  asserts the observable outcome — the `("select", '"Linkedin Jobs"', True)` call
  recorded by `_FakeConn` — not an internal. It would fail against the pre-fix code,
  so it is a genuine RED-first test, not a tautology.

Conditional-vs-unconditional quoting: unconditional quoting would be the more
IMAP-canonical form, but it would contradict two pre-existing assertions
(`test_connect_uses_env_defaults:127` expects bare `merit`,
`test_connect_selects_readonly:186` expects bare `custom-box`), and the executor is
forbidden from touching existing tests. The conditional is the right compromise under
that constraint, not a hack.

### Edge cases missed — all NON-blocking, stated for the record

1. **No astring escaping.** A mailbox name containing `"` or `\` needs those chars
   escaped (`\"`, `\\`) inside a quoted string; a name like `My "Jobs" list` would
   still produce an invalid SELECT. Out of scope for this narrow fix round: no such
   Gmail label exists in the operational facts, and the pre-fix code was equally
   broken there (strictly no regression).
2. **Double-quoting a pre-quoted value.** If a user follows this issue's own comment
   literally and sets the env var to the already-quoted `"Linkedin Jobs"` (quotes
   survive in a `.env`/compose file where a shell would have eaten them), the string
   contains a space and gets wrapped again → `""Linkedin Jobs""`, which fails. Cheap
   hardening if ever wanted: `and not mailbox.startswith('"')`. Not blocking — the
   module's env contract is an unquoted mailbox name, and this is a user-input
   misuse path, not a defect in the fix.
3. **Non-ASCII label names** still need modified-UTF-7 encoding. Pre-existing, untouched,
   out of scope.

None of these are in the failure path B1 named, and none are regressions.

## (b) Existing test assertions — no evidence of modification

I could not run the diff. Static evidence that the fix round respected the constraint:

- Both assertions the brief claims were preserved are present verbatim and consistent
  with pre-fix behavior: `assert ("select", mail.DEFAULT_MAILBOX, True) in fake.calls`
  (line 127) and `assert ("select", "custom-box", True) in fake.calls` (line 186).
  Had either been edited to accommodate the fix, the implementation would not have
  needed the conditional at all — the conditional's existence is itself corroborating
  evidence that the old assertions were left alone.
- The two new tests (`test_mail.py:189`, `test_queue.py:77`) are self-contained additive
  blocks that touch no shared fixture or helper, so they cannot have perturbed
  neighbouring assertions.
- `tests/test_profile.py` is listed as modified in the working tree, but that predates
  this fix round (it is part of the feature branch's own new `strong_terms` surface,
  consumed at `test_queue.py:106`). Nothing in this fix round touches profile behavior.

This is inference, not proof. **Action for the Gate: run `git diff -U0 -- tests/` and
confirm added lines only.** If any `-` line appears in an existing test file, that is
an automatic BLOCK regardless of this review.

## (c) Gate — not verified here

Not runnable (see above). Nothing I read suggests a break: the new code adds no imports,
no long lines beyond the existing style, and no unused names, so I have no static reason
to expect a `ruff` failure. That is an expectation, not a result.

## (d) URL sanitization — correct, does not corrupt legitimate URLs

`merit/queue.py:78` routes `href` through the same `_sanitize()` as title/company.

- `_sanitize` strips `[\x00-\x1f\x7f]` and trims surrounding whitespace. A legitimate
  URL cannot contain raw control characters or spaces — RFC 3986 requires them
  percent-encoded — so no valid URL is altered. Percent-encoded forms (`%1b`, `%20`)
  are untouched, which is the correct behavior: decoding is not this function's job.
- Ordering is sound and conservative: `handle_starttag` gates on the **raw** href
  (`startswith("https://")` and `JOB_URL_MARKER in href`) *before* sanitization, so a
  control char smuggled into the scheme or the `/jobs/view/` marker causes the anchor to
  be dropped rather than laundered into an accepted entry. Sanitization only cleans the
  tail of an already-validated job URL.
- `dedupe_key()` runs on the sanitized url and only keeps scheme+netloc+path, both of
  which were already validated pre-sanitization, so the fix cannot skew dedupe identity.
- `test_parse_alert_strips_control_characters_from_url:77-85` asserts both the negative
  (`"\x1b" not in url`) and the exact resulting string, so it pins behavior rather than
  just absence, and fails without the fix.

## Summary

B1 is genuinely fixed at the right layer, with a behavior-level test that would fail
without it and zero regression on existing mailbox handling. The url-sanitization
follow-up is correct and safe. The remaining astring-escaping and pre-quoted-value
edges are real but out of this fix round's scope and are not regressions — worth a
follow-up note, not a block.

APPROVE is conditional on the Gate confirming (b) tests-added-only and (c) green
pytest + ruff, neither of which I was able to execute.
