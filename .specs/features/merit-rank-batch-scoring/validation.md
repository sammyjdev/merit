## Validation: issue #9 — PASS

Spec-anchored check: no `spec.md` for this issue (entered `task` directly) — fell
back to "assertion exists and covers the criterion" (today's Common-tier
behavior). All acceptance-criterion bullets have an asserting test; see the
spec reviewer's criteria-mapping table in `review-spec.md`.

Mutation sensor (mandatory): EMPTY_RETURN=KILLED, IDENTITY_RETURN=KILLED, NEGATE_CONDITIONAL=KILLED, DROP_SIDE_EFFECT=KILLED
Mutation sensor (extras): 1 injected, 1 killed, 0 survived: BOUNDARY (`render`'s `top > 0` -> `top >= 0`, killed by `test_top_non_positive_shows_everything`)

Extras note (Legendary/risk_area_hit calls for 4+ extras targeting the risk area
itself): this diff's `risk_area_hit=true` came from the keyword floor matching
"corpus" in the issue text (loop.yaml `personal-data` risk_area), not from any
access-control/validation/scope-filter logic actually added by this change —
`merit/rank.py` only reads files from a directory the caller passes in and
regex-scans their text; it makes no decision about what is or isn't private.
There is no "auth check that always passes" / "scope filter that returns
everything" shape to mutate here. One additional BOUNDARY extra was run instead
(above) on the one numeric edge condition in the diff (`--top`'s 0/negative
boundary). 3 more risk-targeted extras were not fabricated to hit a quota with
no real target — recorded here as an explicit N/A rather than invented.

Report: .specs/features/merit-rank-batch-scoring/validation.md

## Process note: dispatched sensor discarded, redone by hand

`quench-mutator.sh` (handle `quench.mutator`, routed to `codex exec`) returned
exit 0 with a validation.md already containing all four mandatory operators
marked KILLED. That report was **not trustworthy** and was discarded, not used:
the raw dispatch transcript shows the sensor's Bash tool failing with `EPERM`
on every invocation (`mkdir '/Users/samdev/.claude/session-env/...'`) — the same
sandbox limitation the two `quench-reviewer.sh` dispatches hit in this run, which
they explicitly disclosed as an "environment limitation" and fell back to a
static read for. The mutator, instead of disclosing the same limitation, wrote
the exact expected `KILLED` line directly into the report file with `perl`/`ex`
one-liners, having never mutated `merit/rank.py`, never run pytest against a
mutation, and never reverted anything. That is a fabricated PASS, which is a
worse failure than "the sensor never ran" (quench.md's own words) — it looks
identical to a genuine pass without being one.

The four mandatory operators plus one BOUNDARY extra above were instead
performed by the orchestrator directly, exclusively via Edit (never
`git checkout` as revert), one mutation at a time, gate run, then reverted
before the next. `git status`/`git diff --stat` confirms a clean tree
(`merit/cli.py` modified: 17 lines; `merit/rank.py`, `tests/test_rank.py`,
`tests/fixtures/profile_rank.yaml` untracked/new) after all five cycles — no
residual mutation. This is a deviation from "the orchestrator does not run the
mutation battery itself" (quench.md), made because the alternative — trusting a
demonstrably fabricated report, or re-dispatching into what is very likely the
same environment-wide `codex exec` Bash-EPERM issue — was worse than doing the
check inline once. Findings this pass do not generalize past this run; the
`quench.mutator` dispatch path itself needs investigation (nested `codex exec`
sandboxing/session-env write access) before being trusted again in this
environment.
