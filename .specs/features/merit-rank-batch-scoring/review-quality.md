# Code-quality review - merit rank batch scoring

Reviewer: `legendary.review.quality` (independent; did not write this code)
Scope: working diff vs `master` -> HEAD
Files: `merit/rank.py` (new), `merit/cli.py` (modified), `tests/test_rank.py` (new),
`tests/fixtures/profile_rank.yaml` (new)

Verdict: APPROVE

## Environment limitation (stated, not glossed over)

`Bash` is unavailable in this reviewer session: every invocation fails with
`EPERM: operation not permitted, mkdir '/Users/samdev/.claude/session-env/...'`,
including with the sandbox override. Therefore I could **not** execute
`git diff`, `ruff`, or `pytest`. This review is a static read of the four files
plus the collaborating modules (`merit/profile.py`, `merit/schemas.py`,
`merit/nodes/match.py`, `merit/mail.py`, `pyproject.toml`). I do **not** claim
the suite is green - that claim belongs to the gate, which can run it.

## Structural check (pre-semantic): existing test files

The branch snapshot shows `M merit/cli.py` plus three untracked additions
(`merit/rank.py`, `tests/test_rank.py`, `tests/fixtures/profile_rank.yaml`).
No pre-existing test file is modified or deleted. **PASS** - no STOP condition.
New tests are RED-before-GREEN by construction (`merit.rank` did not exist).

## Correctness

- **Reuse, not duplication (the issue's explicit constraint).** `score_text`
  resolves every matched term through `merit.profile.resolve`
  (`merit/rank.py:61`) - the same deterministic alias primitive
  `merit/nodes/match.py:33` uses. Status semantics and alias/name/id precedence
  cannot drift between `match` and `rank`. This is the right seam.
- **Word-boundary scan is correct, and non-obviously so.** `(?<!\w)term(?!\w)`
  (`merit/rank.py:44`) instead of `\b...\b` is a real correctness decision, not
  a style one: the fixture skill name `MCP (Model Context Protocol)` ends in
  `)`, and `)` followed by a space is not a `\b` transition, so a `\b`-based
  scan would silently never match that skill.
  `test_paren_terminated_name_matches_verbatim_boundary_regression` pins this
  with a standalone profile so no overlapping alias can mask a regression -
  that test is doing genuine work.
- **Per-skill dedup is keyed on identity, not on term.** `hits[entry.id]`
  (`merit/rank.py:62`) means an alias hit and a skill-name hit for the same
  skill score once; asserted by
  `test_alias_and_name_same_skill_counts_once`.
- **Order independence.** `_compiled_terms` iterates a `set`, so term order
  varies with hash seed - but results aggregate into an id-keyed dict and then
  into counts, so the score is order-invariant. Output order is pinned by
  `sorted(glob(...))` and the total tie-break `(-score, file)`
  (`merit/rank.py:75,84`). No hidden nondeterminism.
- **Batch never aborts.** `rank_dir` catches `OSError` and `UnicodeDecodeError`
  per file and continues (`merit/rank.py:78`). `UnicodeDecodeError` is a
  `ValueError`, not an `OSError`, so listing it explicitly is required, not
  redundant. Matches the contract.
- **Real-corpus compatibility verified by reading the producer.**
  `merit/mail.py:137` writes `---\nfrom:...\nsubject:...\n---\n\n`, which
  `_FRONTMATTER_RE` + `_SUBJECT_RE` match exactly; `corpus/inbox/.seen` and
  `*.md.tmp` are both excluded by the `*.md` glob. The "works today against
  `corpus/inbox/*.md`" criterion holds by construction.
- **No state, no LLM, no network.** `rank` (`merit/cli.py:88-100`) touches
  neither `_db_path()` nor `build_extractor/judge/writer`.
  `test_cli_rank_needs_no_llm_or_state_db` enforces this negatively by
  deliberately *not* monkeypatching them - a well-chosen test.
- **Scope discipline.** No `--deep`, no writes, no approval gate, no new
  dependency. Nothing beyond the contract.

## Security

- Only read access under a user-supplied directory; non-recursive glob; no
  symlink-following amplification beyond what `read_text` already implies.
- No untrusted text reaches a prompt (no LLM in this path), so the
  data-vs-instructions concern from `nodes/match.py` does not apply here.
- Only the single-line title is echoed, with `|` escaped for the table
  (`merit/rank.py:99`); the regex `.` cannot capture a newline, so no row
  injection. Skip reasons carry stdlib exception text only.

## Non-blocking findings

1. `merit/rank.py:88` - **`render`'s `## Skipped` section is never asserted.**
   The *skipping behavior* is covered
   (`test_skipped_unreadable_file_reported_and_others_still_rank`), but only at
   the `rank_dir` boundary; no test asserts `"## Skipped"` or a skip line
   reaches the rendered output. The contract phrases it as a presentation
   requirement ("listed at the end as skipped"), so the presentation half is
   untested. Cheap to close: extend the existing skip test with a
   `render(...)` assertion.
2. `merit/rank.py:52` - **`_temps`-style private parameter in a public
   signature.** Hoisting the compiled terms out of the per-file loop is the
   right perf call, but leaking the cache as an underscore-prefixed public
   parameter is a smell. A module-private `_score_with_terms(...)` plus a thin
   public `score_text(profile, text)` would say the same thing without the
   pseudo-private argument.
3. `merit/cli.py:98` - **`ProfileError` escapes as a traceback** on a bad or
   missing `--profile`, unlike the clean `Exit(1)` given to a bad directory.
   Consistent with the pre-existing `match`/`resume` commands, so fixing it
   here alone would be inconsistent, and out of this issue's scope - noted, not
   charged against this diff.
4. `merit/rank.py:17` - `_HEADING_RE` requires `# ` (single hash), so a posting
   whose only heading is `## Role` falls back to the filename stem. Faithful to
   "first heading" read strictly; flagging only because real recruiter text
   often starts at h2.
5. `merit/rank.py:63` - an alias pointing at a nonexistent skill id makes
   `resolve` return `None` and the term is silently dropped. Arguably profile
   validation's job, not rank's; no warning surface today.
6. `merit/rank.py:89` - `top <= 0` means "show everything". That semantic is
   invented (the contract only specifies `--top N` truncates) but it is
   deliberate and pinned by `test_top_non_positive_shows_everything`.

## Rationale for APPROVE

No correctness, security, or maintainability defect was found. The one design
decision that could have been silently wrong - boundary matching against a
skill name ending in `)` - was identified by the author and pinned with a test
that fails under the naive `\b` implementation. The reuse constraint from the
issue is honored at the correct seam rather than by copying alias logic. The
findings above are quality nits and one genuine but narrow test-coverage gap on
the skipped-file *rendering* path; none of them can produce a wrong ranking or
an aborted batch, so none justifies blocking.

Caveat restated for the gate: `ruff` and `pytest` were **not** run in this
session (Bash EPERM). This approval is on the code as read; execution evidence
must come from the gate.
