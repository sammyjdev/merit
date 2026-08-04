# MERIT - execution plan for fresh sessions

Written 2026-08-03. Repo: `~/dev/products/merit` (`sammyjdev/merit`, default
branch `master`).

This document exists so a session with zero prior context can pick up MERIT and
execute it in the right order. `docs/BACKLOG.md` remains the inventory of what
is open; this file is the sequencing, plus the state that the backlog does not
yet reflect. When the two disagree, re-verify against git before acting.

## State verified on 2026-08-03

- `master` is **9 commits ahead of `origin/master`, unpushed**:
  `0f1639a` rank view, `a241550` rank view finish, `6901454` preventive filters,
  `28c5c27` usability wave, `badbc95` mailbox-scoped UID cursors, `df23407` dark
  redesign, `c468e8f` unified Vagas view, `e2fd6f7` contact capture + follow-up
  radar, `afb3ef4` inmail rows grouped by conversation thread.
- `.axon/context.md` is dirty (generated file, not a change to review).
- **Zero open issues.** The entire backlog lives in `docs/BACKLOG.md`, which
  `forge` does not read. Nothing can enter the loop until issues exist.
- `docs/BACKLOG.md` still carries the 2026-08-01 v0.3a snapshot. None of the
  nine commits above appear in it.
- Five stale worktrees from the Wave 1 lanes, all parked on commits already
  integrated through PRs #18-#21: `lane-a-fila` (17f29bb), `lane-b-dossie`
  (63061d4), `lane-c-pipeline` (163b976), `lane-d-agent` (ade86e1),
  `lane-e-engines` (bf8b2e9).

## Phase 0 - hygiene, before anything else

Until this lands, every agent that reads `docs/BACKLOG.md` is working from a
document that describes a repo state two days old.

1. Push the nine commits. Review the diff first: this is UI and mail-ingestion
   work that was never opened as a PR.
2. Prune the five lane worktrees (`git worktree remove`), and delete the
   `lane/*` branches once confirmed merged.
3. Refresh `docs/BACKLOG.md`: add a status line for the 2026-08-03 work (rank
   view, preventive filters, dark redesign, unified Vagas view, mailbox-scoped
   UID cursors, automatic contact capture with follow-up radar, InMail thread
   grouping) and re-check which "Next in the loop" items the work already
   closed.

This phase is manual. Do not hand it to `forge`.

## Phase 1 - polish batch through the loop

Four small items already listed under "Polish batch" in `docs/BACKLOG.md`:

- narrative writer emits em/en dashes; strip them deterministically in the
  narrative node (the plain-hyphen rule is a standing constraint here)
- `extract` compounds demands ("cost/latency engineering" -> "cost" +
  "latency"), producing noisy gap rows
- golden evaluation prints the agreement rate only on failure; log it on
  success too
- `merit queue` hot list is unordered; reuse rank scoring on titles

Convert them with the `to-issues` skill, label `agent:ready` (the vocabulary
in `.claude/loop.yaml`), then:

    forge run --wip 1

Serial, and each issue stays small. Three of the four are pure functions with
obvious test shapes, which is exactly what the loop is good at.

## Phase 2 - v0.3 service

The only unfinished roadmap item: FastAPI layer mounting the same graph,
Docker, deployed to the existing Coolify VPS. Today `merit serve` is
localhost-only behind a LaunchAgent.

Too large for a single issue. Run `forge blueprint` on it to produce a spec and
a multi-task plan, then execute with `forge task`. Two constraints the
blueprint must carry forward, both non-negotiable:

- personal data (real profile, `corpus/`, inbox files, `~/.merit`) never enters
  git and never enters a container image
- a deployed service changes the threat model that today's localhost-only
  posture assumes; auth is part of the spec, not a follow-up

## Phase 3 - owner decisions, not code

- **PyPI publication as `merit-fit`** (the name `merit` is taken; `merit-fit`
  was verified free on 2026-08-02). Waiting on the owner to seal.
- **`MERIT_API_KEY` (DeepInfra) is absent** from every env and keychain. Store
  it as `merit-deepinfra-key` to re-enable API-engine runs. This blocks any
  re-run of the v1.0 benchmark.
- **Re-sign the Protocol B unsigned commits** (`7e2151f`, `3d7e54d`, and the
  `agent/*` commits merged via PRs #11-#13).
- **LinkedIn skills update**: LangGraph and LangChain (the commits exist).

## Phase 4 - enhancement, only after Phase 2

GNOMON judge panel over report and narrative quality. The v0.25 agreement
experiment (95.4%) used a deterministic scorer, so narrative quality is
currently unmeasured. This is a bridge to `~/dev/tools/gnomon-eval`, not local
work, and it is worth doing only once the service shape is settled.

## Merging (decided 2026-08-04)

Do not use GitHub's rebase merge. It recreates the commit under a new SHA and
does not re-sign it: `2c28040` landed with `verified: false, reason: unsigned`,
while the merge commits it sat next to report `verified: true`. This repo
already tracks re-signing unsigned commits as owner work, so a rebase merge
feeds that debt on every PR.

Land a reviewed PR locally instead - linear history, signatures preserved:

    git fetch origin
    git checkout <branch> && git rebase origin/master
    git push --force-with-lease origin <branch>   # let CI run on what lands
    git checkout master && git merge --ff-only <branch>
    git push origin master

GitHub marks the PR merged on its own, because `--ff-only` keeps exactly the
SHAs the PR already carries. `master` has no branch protection today, so the
direct push is allowed; if that changes, this flow needs a revisit.

## Gate and known traps (from `.claude/loop.yaml`)

- Gate: `.venv/bin/python -m pytest -q -p no:cacheprovider && .venv/bin/ruff check merit tests`
- Setup: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`
- **Inside a worktree, run tests with `PYTHONPATH=$PWD`.** The package is
  installed editable against the main checkout, so without it imports resolve
  to the main checkout's files. This was learned the hard way on 2026-07-28.
- Unit and graph tests are offline by definition. Anything hitting a provider
  is `@pytest.mark.provider` and deselected by default.
- `Interfaces` blocks in `docs/superpowers/plans/*` are contracts. When a plan
  test contradicts one, fix the test, never the contract.
- `risk_areas` in `loop.yaml` force the Legendary tier on keyword match
  (prompt-injection, fetch/SSRF, secrets, personal-data). Expect small issues
  touching those words to route expensive; that is intended.

## Standing constraints

- Scraping LinkedIn is permanently out of scope. Ingestion is the owner's own
  inbox (`InMail` label for recruiter messages, `Linkedin Jobs` label for alert
  digests) plus pasted or URL postings. Fetching alert URLs counts as scraping;
  the queue stores title, company and link only.
- Personal data never enters git. Only synthetic fixtures are committed.

## Recommended order

Phase 0 today, in one sitting. Then Phase 1 as a single `forge run`. Phase 2 is
the next real project and deserves its own session. Phase 3 is a checklist for
the owner and can happen in parallel with any of the above.
