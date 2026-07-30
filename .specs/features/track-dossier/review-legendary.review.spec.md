Verdict: BLOCK

`merit/track.py:126-132` uses a Markdown heading with an ISO UTC timestamp as
the record delimiter, then `show_markdown()` trusts every matching heading
found in the free-form `thread.md` or `notes.md` body. A pasted recruiter
message or a stage note can legitimately contain `## 2025-01-01T00:00:00+00:00`.
That body heading is split into a fabricated second log entry, so the output
does not retain one complete entry and can exclude a real entry from the last
three. This violates the free-form and no-content-parsing constraints.

Reproduced with one `track.log()` body containing `lead-in`, that ISO heading,
and `quoted date heading`: `track show 1` rendered two thread entries instead
of one. Add an observable regression test for a logged body containing an ISO
heading, then use an unambiguous entry boundary before approving.

Structural gate: no existing test file was modified. The new dossier tests
cover the primary CLI behavior, but they only assert that non-timestamp
headings remain within an entry and miss this collision.

Evidence: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q` passed with 191 passed,
1 deselected. `ruff check merit tests` passed. `git diff --cached --check`
passed. The ordinary pytest invocation is blocked before collection by a
machine-global `pytest-rerunfailures` plugin attempting to bind a local socket.

Ponytail: Lean already. Ship after the boundary bug is fixed.
