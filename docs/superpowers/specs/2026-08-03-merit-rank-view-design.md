# MERIT serve: Rank view (InMail ranking surface)

Date: 2026-08-03. Status: approved by owner (chat, 2026-08-03).

## Problem

`merit rank` scores the InMail corpus (`corpus/inbox/*.md`) against the
profile deterministically, but the output dies in the terminal. The serve UI
only surfaces the alert queue (Fila), which has titles but no bodies. The
owner's question - "which vagas, how strong am I, and why" - has no screen.

## Decision

Fifth serve view, `/rank`, computing `rank.rank_dir()` live per request
(sub-second for ~220 files; no snapshot, no cache, no background job).

### Navigation

Topbar reordered to funnel order while the app is young:

```
1 Fila (alerts) - 2 Rank (InMails) - 3 Pipeline - 4 Dossie - 5 Evals
```

`app.js` VIEWS map and existing test asserts follow.

### Screen anatomy

- Header: posting count + one muted line stating the score formula and that
  the real verdict is `merit match` (triage honesty).
- Row (reuses the fila-row grammar: surface card, grid, mono score):
  title link, score, `NF NP NL` breakdown chips (strong in `--accent`,
  partial in `--muted`, gap in `--danger` only when > 0).
- Progressive disclosure: native `<details>` per row; body lazy-loaded via
  `hx-get="/rank/posting/{file}"` on first toggle. Detail partial shows
  matched skill names grouped by status (the "why") above the raw posting
  body in a `<pre>` (no markdown rendering - no new dependency).
- One action per row: **acompanhar** -> `POST /rank/track` ->
  `track.add(source=<inbox file>, status="queued", dossier)` ->
  `HX-Redirect` to `/dossie/{id}`. No discard (no such core operation).
- Cap: `RANK_LIMIT = 50` rows + "mostrar todas (N)" via `?all=1`
  (fila live-smoke lesson).
- Empty state: "rode merit fetch" hint. Skipped files listed muted at the
  bottom, never silent.
- Keyboard: `data-row`/`data-open` contract inherited (j/k/Enter), key `5`.

### Core change (the only one)

`rank.hit_names(profile, text) -> dict[status, list[str]]` - expose the
matched skill names `score_text` already computes internally. Used by the
detail endpoint only; `rank_dir`/`Row` unchanged.

### Security

- Detail/track file parameter: plain-name validation
  (`Path(name).name == name`, `.md` suffix, must exist inside the inbox
  dir) - path traversal returns 404.
- Inbox dir via `MERIT_INBOX` env (default `corpus/inbox`), same pattern as
  the other serve paths. CSP/autoescape contract unchanged; no inline styles.

## Update 2026-08-03 (owner-approved): preventive filters + linear progression

Both list views adopt the same grammar - hidden groups leave the default
list, always counted in a header line with a `?hidden=1` reveal toggle,
never silently dropped:

- **Rank (InMails, body available):** hidden groups are `acompanhando`
  (tracked - source match in the applications table, row links to the
  dossier), `on-site` (`rank.classify_workplace`, hybrid wins over onsite,
  no signal = unknown = visible), `antiga` (frontmatter date, 30+ days via
  `rank.posting_age_days`) and `fraca` (score <= 0). Discard action moves
  the file to `corpus/inbox/discarded/` - filesystem is the state, glob
  does the filtering.
- **Fila (alerts, title only):** score upgraded from strong-term count to
  full `rank.score_text` on the title; hidden groups `on-site` (title
  signal only - the digest carries no location, verified on 7004 entries),
  `antiga` (`queue.is_stale`, alert_date 30+ days) and `fria` (score <= 0).
- **CLI:** `merit queue --prune-days N` physically drops stale entries.
- **Active-check stays out permanently:** validating "still accepting
  applications" requires fetching LinkedIn URLs = scraping (banned; login
  walls/999 make it unreliable anyway). Age is the honest proxy; the real
  check is the owner clicking the finalists.

## Out of scope

Filters/search, profile editing, per-row `merit match` trigger (interrupt
flow does not fit a button today), score distribution charts (Evals owns
aggregates), markdown rendering of bodies.
