"""CLI shell: IO, sessions, and printing. No LLM logic beyond wiring builders."""
import os
import sys
import uuid
from pathlib import Path

import typer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from merit import queue, track
from merit.fetch import fetch_posting
from merit.graph.build import build_graph
from merit.mail import INBOX_DIR, MailError, connect, fetch_messages, ingest_alerts, ingest_messages
from merit.models import build_extractor, build_judge, build_writer
from merit.profile import load_profile, profile_hash, strong_terms
from merit.rank import DEFAULT_TOP, rank_dir
from merit.rank import render as render_rank

app = typer.Typer(add_completion=False)
track_app = typer.Typer(add_completion=False)
app.add_typer(track_app, name="track")

DEFAULT_PROFILE = "profile/profile.yaml"


def _db_path() -> str:
    path = Path(os.environ.get("MERIT_DB", Path.home() / ".merit" / "merit.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _dossier_root() -> Path:
    return Path(_db_path()).parent / "applications"


def _read_posting(posting: str) -> tuple[str, dict]:
    if posting == "-":
        return sys.stdin.read(), {"source": "stdin"}
    if posting.startswith(("http://", "https://")):
        return fetch_posting(posting), {"source": posting}
    return Path(posting).read_text(encoding="utf-8"), {"source": posting}


def _graph(profile_path: str, saver: SqliteSaver):
    profile = load_profile(profile_path)
    return build_graph(profile, build_extractor(), build_judge(), build_writer(), saver)


@app.command()
def match(
    posting: str,
    profile: str = typer.Option(DEFAULT_PROFILE, "--profile"),
    session_id: str | None = typer.Option(None, "--session-id"),
):
    text, meta = _read_posting(posting)
    sid = session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": sid}}
    with SqliteSaver.from_conn_string(_db_path()) as saver:
        graph = _graph(profile, saver)
        graph.invoke(
            {"posting_text": text, "posting_meta": meta, "profile_hash": profile_hash(profile)},
            config,
        )
        report_md = graph.get_state(config).values["report_md"]
    typer.echo(report_md)
    typer.echo(f"\nSession: {sid}")
    typer.echo(f"Resume with: merit resume {sid} --approve | --reject")


@app.command()
def resume(
    session_id: str,
    approve: bool = typer.Option(False, "--approve"),
    reject: bool = typer.Option(False, "--reject"),
    profile: str = typer.Option(DEFAULT_PROFILE, "--profile"),
):
    if approve == reject:
        typer.echo("pass exactly one of --approve / --reject")
        raise typer.Exit(1)
    config = {"configurable": {"thread_id": session_id}}
    with SqliteSaver.from_conn_string(_db_path()) as saver:
        graph = _graph(profile, saver)
        stored = graph.get_state(config).values.get("profile_hash")
        if stored and stored != profile_hash(profile):
            typer.echo("profile changed since report; re-run merit match")
            raise typer.Exit(2)
        result = graph.invoke(Command(resume=approve), config)
    if approve:
        typer.echo(result["narrative_md"])
    else:
        typer.echo("Rejected; session closed.")


@app.command()
def rank(
    directory: str,
    profile: str = typer.Option(DEFAULT_PROFILE, "--profile"),
    top: int = typer.Option(DEFAULT_TOP, "--top"),
):
    posting_dir = Path(directory)
    if not posting_dir.is_dir():
        typer.echo(f"not a directory: {directory}", err=True)
        raise typer.Exit(1)
    prof = load_profile(profile)
    rows, skipped = rank_dir(prof, posting_dir)
    typer.echo(render_rank(rows, skipped, top))


@app.command("ingest-mail")
def ingest_mail(
    out_dir: str = typer.Option(str(INBOX_DIR), "--out-dir"),
    queue_path: str = typer.Option(str(queue.QUEUE_PATH), "--queue-path"),
    full: bool = typer.Option(False, "--full"),
):
    try:
        conn = connect()
    except MailError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None

    cursor_path = Path(out_dir) / ".last-uid"
    if full:
        cursor_path.unlink(missing_ok=True)
    conn.merit_cursor = True
    conn.merit_cursor_path = cursor_path

    try:
        raws = fetch_messages(conn)
    except MailError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    finally:
        conn.logout()
    ingested, skipped = ingest_messages(raws, Path(out_dir))
    queued, alert_skipped = ingest_alerts(raws, Path(queue_path))
    for item in ingested:
        typer.echo(str(item.path))
        typer.echo(f"  merit match {item.path}")
    for reason in skipped:
        typer.echo(reason, err=True)
    for reason in alert_skipped:
        typer.echo(reason, err=True)
    typer.echo(f"ingested {len(ingested)}, skipped {len(skipped)}", err=True)
    typer.echo(f"queued {len(queued)}", err=True)
    typer.echo("  merit queue", err=True)


@app.command("queue")
def queue_cmd(
    queue_path: str = typer.Option(str(queue.QUEUE_PATH), "--queue-path"),
    all_: bool = typer.Option(False, "--all"),
    profile: str = typer.Option(DEFAULT_PROFILE, "--profile"),
):
    entries = queue.load_entries(Path(queue_path))
    if not entries:
        typer.echo("No queued postings yet. Run `merit ingest-mail` to check for job alerts.")
        return
    terms = strong_terms(load_profile(profile))
    hot = [e for e in entries if queue.is_hot(e.title, terms)]
    cold = [e for e in entries if not queue.is_hot(e.title, terms)]

    for e in hot:
        typer.echo(f"[hot] {e.title} - {e.company or 'unknown company'}")
        typer.echo(f"  {e.url}")
    if all_:
        for e in cold:
            typer.echo(f"[cold] {e.title} - {e.company or 'unknown company'}")
            typer.echo(f"  {e.url}")

    typer.echo("\nFull match requires pasting the description: merit match -")


@track_app.command("add")
def track_add(
    source: str,
    title: str | None = typer.Option(None, "--title"),
    company: str | None = typer.Option(None, "--company"),
    status: str = typer.Option("found", "--status"),
    note: str | None = typer.Option(None, "--note"),
    session: str | None = typer.Option(None, "--session"),
    create_dir: bool = typer.Option(False, "--dir"),
):
    try:
        app_id = track.add(
            _db_path(),
            source,
            title=title,
            company=company,
            status=status,
            note=note,
            session_id=session,
            dossier_root=_dossier_root() if create_dir else None,
        )
    except track.TrackError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"added {app_id}")


@track_app.command("set")
def track_set(
    app_id: int,
    status: str,
    note: str | None = typer.Option(None, "--note"),
):
    try:
        track.set_status(_db_path(), app_id, status, note=note)
    except track.TrackError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"{app_id} -> {status}")


@track_app.command("list")
def track_list(status: str | None = typer.Option(None, "--status")):
    try:
        typer.echo(track.list_markdown(_db_path(), status=status))
    except track.TrackError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


@track_app.command("log")
def track_log(
    app_id: int,
    text: str = typer.Argument("-"),
    file: str = typer.Option("thread", "--file"),
):
    body = sys.stdin.read() if text == "-" else text
    try:
        track.log(_db_path(), app_id, body, file=file, dossier_root=_dossier_root())
    except track.TrackError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"logged to {file} for {app_id}")


@app.command("serve")
def serve(
    port: int = typer.Option(4321, "--port"),
    install_agent: bool = typer.Option(False, "--install-agent"),
    uninstall_agent: bool = typer.Option(False, "--uninstall-agent"),
):
    if install_agent and uninstall_agent:
        typer.echo("pass exactly one of --install-agent / --uninstall-agent")
        raise typer.Exit(1)

    if install_agent:
        from merit.serve import agent as launch_agent

        binary = launch_agent.resolve_binary()
        written = launch_agent.install_agent(Path.home(), binary, port)
        typer.echo(str(written))
        typer.echo(f"launchctl load {written}")
        return

    if uninstall_agent:
        from merit.serve import agent as launch_agent

        if launch_agent.uninstall_agent(Path.home()):
            typer.echo("LaunchAgent removed")
        else:
            typer.echo("No LaunchAgent installed")
        return

    import uvicorn

    from merit.serve.app import HOST, create_app

    assert HOST == "127.0.0.1"  # noqa: S101
    typer.echo(f"MERIT serve on http://{HOST}:{port} (localhost only)")
    uvicorn.run(create_app(), host=HOST, port=port, log_level="warning")


@track_app.command("show")
def track_show(app_id: int):
    try:
        typer.echo(track.show_markdown(_db_path(), app_id))
    except track.TrackError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
