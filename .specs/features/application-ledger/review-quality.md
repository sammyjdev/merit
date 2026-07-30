# Code-quality review

Verdict: APPROVE

## Scope

`master` is the resolved base branch. `HEAD` currently equals `master`, so the literal
`master...HEAD` diff is empty; the candidate implementation is uncommitted. I reviewed
the complete worktree delta against `master`, including the new untracked files.

The structural test gate passes: `tests/test_track.py` is new, and no existing test file
was modified.

## Reasoning

No blocking correctness, security, or maintainability finding was identified.

- The persistence layer is small and direct: one module, stdlib `sqlite3`, parameterized
  statements, scoped updates, explicit transactions, and no new dependency or abstraction.
- Every supported write validates the closed status set before opening or mutating the
  database. A failed update names the missing application and rolls back.
- The schema matches the contract and is created lazily in the same `MERIT_DB` file used
  by the existing CLI. UTC timestamps are ISO formatted and `created_at` is preserved on
  transitions.
- Listing performs one query, not an N+1 sequence. Its unbounded result matches the
  explicit local-ledger contract; pagination or an index would be speculative at this
  scale.
- SQL values are bound parameters. Markdown cells escape table separators and flatten
  newlines, preventing notes from forging extra table columns or rows.
- The tests exercise the public CLI against real temporary SQLite files and inspect the
  resulting persisted state. They cover default add, invalid writes, targeted transitions,
  note preservation, missing ids, status filtering, empty output, and UTC timestamps.
- The risk-area mutations named by the issue are materially covered: invalid-status
  acceptance, skipped write validation, mis-scoped updates, and a disabled list filter all
  contradict existing assertions.
- No ADR is required for this delta because the issue itself fixes the architectural
  choice: a lazily created table in the existing SQLite database.

## Verification

- `pytest -p no:rerunfailures -q`: 92 passed, 1 deselected.
- `pytest -p no:rerunfailures -q tests/test_track.py`: 14 passed.
- `ruff check .`: all checks passed.
- CLI help through `CliRunner`: `track add`, `track set`, and `track list` are registered.

The global `pytest-rerunfailures` plugin was disabled because its session setup opens a
local socket, which this sandbox forbids before test collection. This does not alter the
project test selection or assertions.

## Non-blocking notes

1. `validation.md` reports four extra mutations but names only
   `SET_STATUS_DROP_WHERE`. The counts are consistent with the exercised behavior, but
   naming all four injected mutants would make the audit trail independently reproducible.
2. `--session` is wired directly to `session_id`, but the tests assert only its default
   null value. A non-null round-trip assertion would strengthen this contract edge.
