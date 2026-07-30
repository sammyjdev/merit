# Spec review - merit rank: batch scoring over a directory of postings

Verdict: APPROVE

Reviewer: independent spec reviewer (legendary.review.spec). Read-only pass over
the working tree (`merit/rank.py`, `tests/test_rank.py`,
`tests/fixtures/profile_rank.yaml`, `merit/cli.py`) plus the reused
`merit/profile.py`, `merit/nodes/match.py`, `merit/schemas.py`, `pyproject.toml`.

## Structural check: existing test files

No modification to any pre-existing test file. The change set is
`merit/cli.py` (modified: one import pair + one new `rank` command) and three new
untracked files (`merit/rank.py`, `tests/test_rank.py`,
`tests/fixtures/profile_rank.yaml`). RED-phase new tests only. No STOP condition.

## Criteria mapping

| Criterion | Asserting test | Status |
|---|---|---|
| `merit rank <dir> [--profile P] [--top N]` | `test_cli_rank_happy_path`, `test_cli_rank_top_flag` | covered |
| Deterministic, no LLM / no network / no state | `test_cli_rank_needs_no_llm_or_state_db` (deliberately leaves `build_extractor/judge/writer` unpatched and unsets `MERIT_DB`) | covered |
| Weighted hits strong=+2 / partial=+1 / gap=-1 | `test_alias_hit_scores_as_strong`, `test_partial_skill_name_hit_via_fixture`, `test_gap_penalty_alone`, `test_gap_combined_with_strong_exact_score` | covered |
| Alias hit vs skill-name hit | `test_alias_hit_scores_as_strong` / `test_skill_name_hit_scores_as_strong` / `test_alias_and_name_same_skill_counts_once` | covered |
| Case-insensitive, word-boundary scan | `test_boundary_false_positive_does_not_match_substring`, `test_paren_terminated_name_matches_verbatim_boundary_regression` | covered |
| Ranking order | `test_ranking_order_across_three_postings` (order + exact scores) | covered |
| Title = first heading or `subject:` frontmatter | `test_title_frontmatter_subject_wins_over_heading`, `test_title_heading_used_when_no_frontmatter`, `test_title_filename_stem_fallback_when_neither`, `test_title_subject_with_colon_parses_correctly` | covered |
| Unreadable file listed as skipped, batch never aborts | `test_skipped_unreadable_file_reported_and_others_still_rank` | covered |
| `--top N` truncation, default 20 | `test_top_truncation_default_and_explicit` (25 postings -> 20 default, 5 explicit) | covered |
| Reuse the deterministic alias stage, do not duplicate | `merit/rank.py:61` calls `merit.profile.resolve` - the same resolver `merit/nodes/match.py:33` uses | satisfied |
| No new dependencies | `merit/rank.py` imports only `re`/`pathlib`/`typing` + internal modules; `pyproject.toml` untouched | satisfied |
| Non-goal: no `--deep`, no writes | `rank` command has no third flag; `rank_dir`/`render` are pure, no `_db_path()` call, no `SqliteSaver` | satisfied |

Nothing extra of substance: the two behaviors beyond the literal contract are
markdown pipe-escaping in titles (`render`, needed for a correct table, tested by
`test_title_with_pipe_is_escaped_in_rendered_table`) and `--top <= 0` meaning
"show all" (`test_top_non_positive_shows_everything`). Both are small and tested.

## Test quality

Tests assert observable behavior (exact score tuples, file order, rendered
markdown, CLI exit codes), not internals. The boundary regression test at
`tests/test_rank.py:80` is the strongest one: because `MCP (Model Context
Protocol)` ends in `)`, a `\b`-based pattern cannot match it, and the test builds
a standalone `Profile` with no overlapping alias so nothing else can rescue the
hit - it genuinely fails without the lookaround implementation. The scoring and
ordering tests likewise fail against an empty `merit/rank.py`.

## Non-blocking notes (for the author, not fix-required)

1. `score_text` exposes a private cache parameter `_terms` in its public
   signature (`merit/rank.py:52`). A module-private `_score_text(profile, text,
   terms)` with a thin public wrapper would read cleaner; behavior is correct as-is.
2. `merit rank --profile <missing-or-invalid>` lets `ProfileError` escape as a
   traceback rather than a `typer.Exit`. This matches the existing behavior of
   `match`/`resume`, so it is pre-existing repo style, not a regression from this
   change.
3. `hits` in `score_text` is the only unannotated local in an otherwise annotated
   module.

## Verification limitation (disclosed)

The Bash tool was unavailable for this review (every invocation, including with
the sandbox disabled, failed with `EPERM: operation not permitted, mkdir
/Users/samdev/.claude/session-env/...`). I could therefore not execute `pytest`
or `ruff` myself, and I did not run `git diff` - the change set was determined
from the session's git-status snapshot plus direct file reads. Judgments above are
from static reading. Specifically checked by hand instead of by tool:

- Fixture/`Profile` construction is valid against `merit/schemas.py` (`evidence`
  and `claims` default to empty lists, so `SkillEntry(id=..., name=...,
  status=...)` validates).
- ruff: the configured `line-length = 100` is not enforced, because `E501` is
  outside ruff's default select and `extend-select = ["S", "I", "ISC", "RUF"]`
  does not add it - so the two ~101-106 char test lines are not violations. The
  split `from merit.rank import DEFAULT_TOP, rank_dir` /
  `from merit.rank import render as render_rank` in `merit/cli.py:16-17` is the
  isort-canonical form under the default `combine-as-imports = false`, so `I001`
  should not fire.

The gate stage still owns the authoritative `ruff` + `pytest` run. If that run is
red, this APPROVE does not cover it.
