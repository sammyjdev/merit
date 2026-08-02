# MERIT serve Wave 1 - lane plan

> For agentic workers: executed by codex-lane / agy-lane under the session
> orchestrator. Each lane: own worktree from master (3d6eef8+), serial tasks,
> TDD (red test first), gate `PYTHONPATH=$PWD pytest tests/ -q && ruff check
> merit/ tests/`, commit per task, never merge. GPG failure at commit: write
> message to .forge-commit-msg-<lane>.txt, report, stop (Protocol B).

**Goal:** fill the three view stubs + LaunchAgent/hardening on the Wave 0
skeleton. Spec: docs/superpowers/specs/2026-07-30-merit-serve-ui-design.md
(visual tokens are RESOLVED there - consume tokens.css variables verbatim,
never invent colors/spacing; plain hyphens only in all copy).

## Global constraints

- Routes call existing modules (`merit.queue`, `merit.track`, `merit.rank`,
  `merit.profile`) - no SQL outside merit/track.py, no business logic in views.
- Never touch another lane's files. Shared files are OFF-LIMITS except where
  a task explicitly names them.
- No state-changing GET. htmx posts return partial HTML fragments.
- Tests: TestClient + tmp_path fixtures (MERIT_DB env + queue file path
  injection); never ~/.merit. New tests in the lane's own test file.
- All UI copy pt-BR, plain hyphen only. Scores/timestamps in `var(--mono)`.

## Interfaces produced by Wave 0 (consume, do not modify)

- `merit.serve.rendering.page(request, template, context)` - full page.
- `templates/base.html` blocks: `{% block content %}`; context key `view`.
- Row selection contract for keyboard JS: each selectable row = `data-row`
  attr; its open link = `a[data-open]`. Help overlay id: `keys-help`.
- tokens.css classes: `.muted`; everything else via CSS variables.

---

## Lane A (codex) - Fila view

**Files:** `merit/serve/views/fila.py` (replace stub), `templates/fila.html`,
`templates/_fila_rows.html` (partial), `tests/test_serve_fila.py`.

**Contract:**
- `GET /fila` - hot entries (queue.load_entries + profile.strong_terms +
  queue.is_hot), ranked desc by rank-style strong-hit count on title, each
  row: title, company, mono score badge, actions. Cold count shown;
  `GET /fila?all=1` includes cold rows after hot.
- `POST /fila/discard` (form: url) - removes entry from queue file (add
  `queue.discard(path, url)` to merit/queue.py - the ONE shared-file
  exception for this lane), returns refreshed `_fila_rows.html` partial.
- `POST /fila/track` (form: url, title, company) - `track.add` with
  dossier (source=url, status=queued, dossier_root=~/.merit/applications
  via cli._dossier_root pattern - inject root in tests), responds
  `HX-Redirect: /dossie/{id}`.
- Rows carry `data-row`; LinkedIn link `target=_blank rel=noopener` and a
  `a[data-open]` pointing at the row's primary action.

**Acceptance tests (write first, verbatim):**
```python
# tests/test_serve_fila.py - fixtures: tmp queue.json with 2 hot + 1 cold
# entry (profile fixture with one strong term matching the 2 hot titles),
# MERIT_DB tmp, dossier root tmp.
def test_fila_lists_hot_ranked_and_hides_cold_by_default(client): ...
    # asserts: both hot titles present in order, cold title absent,
    # "frias" toggle shows count 1
def test_fila_all_includes_cold(client): ...
def test_discard_removes_from_queue_and_returns_partial(client): ...
    # POST /fila/discard -> 200, discarded title absent, queue file shrunk
def test_track_creates_application_and_redirects(client): ...
    # POST /fila/track -> HX-Redirect header /dossie/1; track.list shows row
def test_fila_rows_have_keyboard_contract(client): ...
    # data-row present, a[data-open] present per row
```

## Lane B (codex) - Dossie view

**Files:** `merit/serve/views/dossie.py` (replace stub),
`templates/dossie.html`, `templates/_dossie_log.html`,
`tests/test_serve_dossie.py`. Shared-file exception: add read accessor
`track.entries(db_path, app_id) -> list[(stamp, source, body)]` (full
history, chronological) to merit/track.py - additive only.

**Contract:**
- `GET /dossie` - index: list of applications (track rows) as `data-row`
  links to `/dossie/{id}`.
- `GET /dossie/{id}` - status stepper (closed set in order; current
  highlighted; click = `POST /dossie/{id}/status` form value), JD panel
  (jd.md text, pre-wrap), thread + notes panels with full history
  (newest last), one textarea per panel posting to
  `POST /dossie/{id}/log` (form: file=thread|notes, text) returning
  refreshed `_dossie_log.html` partial. 404 page for unknown id.
- Legacy row without dossier: panels show "sem dossie - registre a
  primeira entrada" and the log POST creates it (track.log already does).

**Acceptance tests (verbatim):**
```python
def test_dossie_index_lists_applications_with_row_contract(client): ...
def test_dossie_renders_stepper_jd_thread_notes(client): ...
    # seeded app with dossier: current status highlighted, jd text shown,
    # thread + notes entries all rendered (not just last 3)
def test_status_change_via_post_updates_row(client): ...
def test_log_post_appends_and_returns_partial(client): ...
def test_log_pasted_entry_header_line_stays_content(client): ...
    # reuse the phantom-boundary fixture idea from test_track_dossier
def test_unknown_id_404s(client): ...
def test_thread_content_is_escaped(client): ...
    # log body "<script>alert(1)</script>" renders escaped
```

## Lane C (agy) - Pipeline view

**Files:** `merit/serve/views/pipeline.py` (replace stub),
`templates/pipeline.html`, `templates/_pipeline_board.html`,
`tests/test_serve_pipeline.py`.

**Contract:**
- `GET /pipeline` - kanban: one column per active status (found, queued,
  applied, screening, interview, offer), closed statuses (rejected,
  withdrawn) collapsed in one "encerradas" column with count; cards =
  title, company, mono updated_at date; card is `data-row`, `a[data-open]`
  -> `/dossie/{id}`; column header shows count.
- `POST /pipeline/{id}/move` (form: status) via track.set_status; invalid
  status -> 422 with named error text; returns refreshed board partial.
  Move controls: per-card select or prev/next buttons - executor's choice,
  keyboard-reachable either way.
- Empty state: "pipeline vazio - promova vagas na Fila".

**Acceptance tests (verbatim):**
```python
def test_pipeline_columns_and_counts(client): ...
def test_closed_statuses_collapse_into_encerradas(client): ...
def test_move_updates_status_and_returns_board(client): ...
def test_move_invalid_status_422_named_error(client): ...
def test_cards_have_keyboard_contract_and_dossie_links(client): ...
def test_empty_state(client): ...
```

## Lane D (agy) - LaunchAgent + hardening

**Files:** `merit/serve/agent.py` (new), `merit/cli.py` (ONLY the serve
command body - no other command), `tests/test_serve_agent.py`,
`README.md` (serve section append).

**Contract:**
- `merit serve --install-agent` writes
  `~/Library/LaunchAgents/com.sammyjdev.merit-serve.plist` (KeepAlive,
  RunAtLoad, ProgramArguments = resolved merit binary + serve + --port,
  StandardOut/ErrPath ~/.merit/serve.log), prints `launchctl load` hint,
  does NOT load it itself. `--uninstall-agent` removes the plist.
  Path building/rendering in merit/serve/agent.py (pure, testable,
  home injected); cli command stays thin.
- `merit serve` refuses `--host` entirely (no such option) and asserts
  HOST == "127.0.0.1" before uvicorn.run (belt and braces).
- README: how to run, install the agent, where logs live, that the
  server is localhost-only by design.

**Acceptance tests (verbatim):**
```python
def test_plist_rendered_with_keepalive_and_localhost_port(tmp_path): ...
def test_install_and_uninstall_roundtrip(tmp_path, monkeypatch): ...
def test_plist_program_arguments_use_absolute_binary(tmp_path): ...
def test_serve_has_no_host_option(): ...  # CliRunner --help
```

---

## Lane/wave map

Wave 1 (parallel): A+B on the codex rail, C+D on the agy rail.
Wave 2 (orchestrator): serial merges A->B->C->D (disjoint files - expect
zero conflicts), browser smoke, impeccable finish pass, backlog refresh.
Lane E (v0.3b engines+otel) dispatches when a rail frees; separate plan.
