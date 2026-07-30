Mutation sensor (mandatory): EMPTY_RETURN=KILLED, IDENTITY_RETURN=KILLED, NEGATE_CONDITIONAL=KILLED, DROP_SIDE_EFFECT=KILLED
Mutation sensor (extras): 4 injected, 4 killed, 0 survived: SET_STATUS_DROP_WHERE (fixed - see below)

Fix round: SET_STATUS_DROP_WHERE originally SURVIVED (dropping `WHERE id = :id` from
`set_status`'s UPDATE passed all 13 existing tests, since none of them ever had more
than one row in the table to accidentally corrupt). Maker added
`test_set_status_only_updates_targeted_row_when_multiple_exist` to `tests/test_track.py`
(seeds 2 applications, `set`s only one, asserts the other row is byte-identical
before/after). Orchestrator re-verified directly: re-applied the DROP_WHERE mutation via
Edit, confirmed the new test fails (1 failed, 2 passed on `-k set_status`), then reverted
via Edit (not `git checkout`) and confirmed the full gate is green again (92 passed, ruff
clean). Mutant now KILLED.
