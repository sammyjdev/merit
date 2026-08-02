# MERIT serve: local server + 3-view UI (v0.3a)

Status: approved by owner 2026-07-30 (navigation and stack chosen via review).
Executors: codex-lane and agy-lane under the session orchestrator (house
pattern from phase 1). Design decisions are resolved in the plan, not
delegated to executors.

## Goal

A local, always-available web UI on the owner's Mac for the daily loop:
triage the queue, track applications through stages, and keep the full
dossier (JD, recruiter thread, notes) per application - without the
terminal and without data ever leaving the machine.

## Non-goals (v0.3a)

- No auth (localhost single-user by construction).
- No subscription LLM backend yet (v0.3b swaps the engine; UI unchanged).
- No deep-match orchestration from the UI beyond triggering the existing
  graph via a background thread; no SSE/streaming yet.
- No React; no build step; no new JS beyond htmx + ~50 lines vanilla.

## Architecture

- `merit serve [--port 4321]` - FastAPI app bound to `127.0.0.1` ONLY
  (hard-coded host; refuse `0.0.0.0`). Server-rendered Jinja2 templates,
  htmx for partial updates. New deps: `fastapi`, `uvicorn`, `jinja2`
  (htmx vendored as a single static file - no CDN at runtime).
- Thin service layer: routes call existing modules (`merit.queue`,
  `merit.track`, `merit.rank`, `merit.profile`) - no business logic in
  routes, no SQL outside `merit/track.py`.
- State stays where it is: `MERIT_DB` sqlite + `~/.merit/applications/`
  dossiers + `corpus/` files. The server is a viewer/editor over them.
- LaunchAgent `com.sammyjdev.merit-serve.plist` (KeepAlive, RunAtLoad,
  localhost port) installed by `merit serve --install-agent`; logs to
  `~/.merit/serve.log`.

## The 3 views (the only navigation that exists)

Top bar: `[1 Fila] [2 Pipeline] [3 Dossiê]` + global keyboard: `1/2/3`
switch views, `j/k` move row selection, `Enter` opens, `?` shows keys.
No nested menus. Deep-link URLs: `/fila`, `/pipeline`, `/dossie/{id}`.

1. **Fila** (`/fila`): hot queue entries (existing `queue.load_entries` +
   `is_hot`), ranked. Row actions (htmx buttons + keys): `d`escartar
   (removes from queue file), `t`rack (creates application + dossier,
   jumps to its Dossiê), open LinkedIn link in new tab. Cold entries
   behind a single "mostrar frias" toggle.
2. **Pipeline** (`/pipeline`): kanban columns = the closed status set
   (found, queued, applied, screening, interview, offer, rejected,
   withdrawn; the last two collapsed under "encerradas"). Cards show
   title/company/updated_at. Move = htmx PATCH via existing
   `track.set_status`. Card click -> Dossiê.
3. **Dossiê** (`/dossie/{id}`): everything about one application:
   status stepper (click to advance), JD panel (rendered jd.md),
   thread panel with paste-textarea -> `track.log(file="thread")`,
   notes panel -> `track.log(file="notes")`, full log history
   (all entries, not just last 3 - add `track.entries()` accessor).

## Visual direction (RESOLVED via house design stack 2026-08-01; verbatim)

Engine decision (ui-ux-pro-max): teal technical palette + single action
orange, dashboard/data mood. Adapted by authority rules: fonts go system
stack + `ui-monospace` for data (Google Fonts CDN violates the CSP);
landing-page pattern discarded (3-view tool keeps density direction).
Dials: VARIANCE 3, MOTION 1 (150ms hovers only + prefers-reduced-motion),
DENSITY 8. Impeccable pass at integration wave is the final authority.

Tokens (tokens.css, executors copy verbatim):
  --bg:#F7FAF9; --surface:#FFFFFF; --ink:#16342F; --muted:#5C7570;
  --line:#DCE7E4; --accent:#0F766E; --accent-weak:#E6F2F0;
  --cta:#C2410C; --danger:#B42318;
  font: system-ui stack; data/scores/timestamps in ui-monospace;
  spacing scale 4/8/12/16/24/32; radius 6px; no shadows deeper than
  0 1px 2px rgba(22,52,47,.06); focus ring 2px var(--accent).
Contrast floor 4.5:1; cursor-pointer on clickables; no emoji icons;
plain hyphens only in all copy - never em/en dashes.

## Security

- Bind 127.0.0.1; assert at startup, test-enforced.
- All rendered content from dossiers/queue is user-owned text: escape
  by default (Jinja autoescape on); recruiter-thread text is untrusted
  input for XSS purposes.
- No external requests from served pages (htmx vendored; CSP header
  `default-src 'self'`).
- Queue discards and status moves are POST/PATCH (no state-changing GET).

## Testing

- FastAPI TestClient; tmp_path DB + dossier fixtures (never ~/.merit).
- Route tests per view: render, action, htmx partial shape.
- Keyboard/JS untested (50 lines, manual smoke); CSP + bind tests explicit.
- Gate: existing 192 tests keep passing untouched + new suite; ruff clean.

## Phases (skills-closure mapping decided 2026-08-01)

- v0.3a (this spec): serve + 3 views + LaunchAgent.
- v0.3b "engines + observability" (one lane, adjacent files):
  - Claude Agent SDK backend as `MERIT_MODEL=claude-subscription`
    (langchain wrapper in merit/models.py); zero UI change.
  - Vertex AI judge backend (`MERIT_MODEL=vertex`, langchain-google-vertexai)
    - closes the GCP/Vertex profile gap the honest way (owner provides a
    GCP project, ~15 min).
  - OpenTelemetry instrumentation of merit serve: per-request traces +
    per-graph-node spans, OTLP/console exporter - closes the OTel gap.
- v0.25: LangSmith dataset + GNOMON judge (promotes LangSmith to strong).
- v1.0: METRON benchmark (pre-registered; runs on API engines, not
  subscription, for reproducibility).
- Post-1.0 optional: React UI v2 as a separate portfolio project (React
  gap is NOT forced into this repo - HTMX was a deliberate choice).
- Later: SSE progress for deep match from the UI; queue triage overlay.
- Declared out (honesty rule): PyTorch/TensorFlow/classic MLOps and
  Bedrock AgentCore have no natural fit here; they stay declared gaps.
