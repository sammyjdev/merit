# Spec review — merit track: application ledger (issue #10)

Verdict: APPROVE

## Structural pre-check (test-file diff)

`git status` / `git diff master` show three touched paths: `merit/cli.py` (modified, +51,
non-test), `merit/track.py` (new), `tests/test_track.py` (new). **No existing test file was
modified** — `tests/test_track.py` is entirely new. No STOP condition.

## Criteria coverage

| Criterion | Asserting test | OK |
|---|---|---|
| `add <source>` defaults, optional flags | `test_add_defaults_status_found_and_matches_timestamps`, `test_add_with_all_options_persists_exactly` | yes |
| default status `found` | same (asserts `row["status"] == "found"`) | yes |
| invalid status rejected with named error | `test_add_invalid_status_exits_1_and_inserts_nothing`, `test_module_add_invalid_status_raises_track_error`, `test_set_invalid_status_leaves_row_completely_unchanged` (message names the value and the valid set) | yes |
| `set <id> <status> [--note]` transitions | `test_set_status_updates_note_and_updated_at`, `test_set_status_without_note_preserves_existing_note`, `test_set_nonexistent_id_exits_1_and_names_id` | yes |
| `list` markdown table with the 6 required columns, ordered | `test_list_markdown_table_ordered_by_id_missing_title_renders_dash` (header asserted byte-exact) | yes |
| `list --status S` filter | `test_list_filters_by_status` (asserts the excluded row is absent, not just the included one present) | yes |
| empty list output | `test_list_empty_table_prints_no_applications` | yes |
| closed status set (8 values) | `merit/track.py:6` matches the issue exactly; `_validate` called before every INSERT/UPDATE and on the list filter | yes |
| schema/columns + lazy creation | `_CREATE_TABLE_SQL` (`IF NOT EXISTS` in `_conn`) has exactly the specified columns; verified by `SELECT *` assertions | yes |
| same SQLite file as `MERIT_DB` | CLI passes `_db_path()`; tests set `MERIT_DB` via monkeypatch | yes |
| `--session` traceability | plumbed `add(..., session_id=session)`; default-`None` asserted. Non-default path (a real session id round-trip) is **not** asserted — noted below, not blocking | partial |
| ISO UTC timestamps | `test_timestamps_are_utc_iso_and_recent` (asserts `+00:00` suffix and freshness) | yes |
| stdlib sqlite3 only, no new deps | `merit/track.py` imports only `contextlib`, `sqlite3`, `datetime`; no dependency manifest change in the diff | yes |
| ruff + pytest green | verified by me: `ruff check .` → "All checks passed!"; `pytest -q` → 92 passed, 1 deselected | yes |

## Tests target behavior, not implementation

Assertions go through the CLI (`CliRunner`) and read back through SQL on the real
on-disk DB. The only internal reach-in is `track._conn` used as a read handle in tests
— acceptable, it is a connection helper, not the logic under test. Each test would fail
without the implementation (the module does not exist on `master`).

## Mutation sensor

`validation.md` reports 4/4 mandatory killed and the 4 extras with `SET_STATUS_DROP_WHERE`
initially surviving, then killed by a *new* test
(`test_set_status_only_updates_targeted_row_when_multiple_exist`) — the correct remedy
(add coverage), not a weakened assertion. I re-read that test: it snapshots row 2 whole
and asserts `other_after == other_before`, so it genuinely dies under a dropped/mis-scoped
`WHERE`. The extras line format matches the required form, though the `<list>` field names
the fixed mutant rather than being empty — cosmetic.

Risk area (`personal-data`): the ledger writes only owner-supplied values, uses named
parameters everywhere (no string-built SQL), and `_cell` escapes `|` and newlines so a
note cannot forge table structure on stdout. The status filter is a real equality
predicate on a validated value.

## Nothing extra

No sync, reminders, or analytics; no speculative abstraction; no config. The `_cell`
dash/escape helper and the `COALESCE(:note, note)` note-preservation are the only
behaviors beyond the literal contract, both required to render/update sanely and both
covered by tests.

## Non-blocking notes for the author

1. `--session` has no test where a session id is actually stored and read back; the
   contract bullet is thin but a one-line assertion in
   `test_add_with_all_options_persists_exactly` would close it.
2. `test_list_markdown_...:186` accepts two shapes of separator row and `:192` asserts
   `" - " in lines[3]`, which is positional and loose. The exact header assertion on
   `lines[0]` carries the real weight, so this is style, not a gap.
3. `cur.lastrowid` is `int | None` per typeshed while `add` is annotated `-> int`; ruff
   does not run a type checker here, so it passes, and the value is never `None` after a
   successful single-row INSERT.
