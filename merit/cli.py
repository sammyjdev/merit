"""CLI shell: IO, sessions, and printing. No LLM logic beyond wiring builders."""
import os
import sys
import uuid
from pathlib import Path

import typer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from merit.fetch import fetch_posting
from merit.graph.build import build_graph
from merit.models import build_extractor, build_judge, build_writer
from merit.profile import load_profile, profile_hash

app = typer.Typer(add_completion=False)

DEFAULT_PROFILE = "profile/profile.yaml"


def _db_path() -> str:
    path = Path(os.environ.get("MERIT_DB", Path.home() / ".merit" / "merit.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


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
