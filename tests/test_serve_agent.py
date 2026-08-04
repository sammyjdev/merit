import pytest
import typer.main
from typer.testing import CliRunner

from merit.cli import app
from merit.serve import agent
from merit.serve.agent import (
    LABEL,
    install_agent,
    log_path,
    plist_path,
    render_plist,
    resolve_binary,
    uninstall_agent,
)


def test_plist_and_log_path_helpers(tmp_path):
    p_path = plist_path(tmp_path)
    l_path = log_path(tmp_path)
    assert p_path == tmp_path / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    assert l_path == tmp_path / ".merit" / "serve.log"


def test_plist_rendered_with_keepalive_and_localhost_port(tmp_path):
    plist = render_plist(tmp_path, "/usr/bin/merit", 4321)
    assert plist["KeepAlive"] is True
    assert plist["RunAtLoad"] is True
    assert plist["ProgramArguments"] == ["/usr/bin/merit", "serve", "--port", "4321"]
    assert str(tmp_path) in plist["StandardOutPath"]
    assert str(tmp_path) in plist["StandardErrorPath"]
    assert plist["StandardOutPath"] == plist["StandardErrorPath"]
    assert plist["Label"] == LABEL


def test_install_and_uninstall_agent_direct(tmp_path):
    written = install_agent(tmp_path, "/usr/local/bin/merit", 4321)
    assert written.exists()
    assert written == plist_path(tmp_path)

    removed = uninstall_agent(tmp_path)
    assert removed is True
    assert not written.exists()

    removed_again = uninstall_agent(tmp_path)
    assert removed_again is False


def test_install_and_uninstall_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "shutil.which", lambda cmd: "/usr/local/bin/merit" if cmd == "merit" else None
    )

    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--install-agent", "--port", "4321"])
    assert result.exit_code == 0

    expected_plist = tmp_path / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    assert expected_plist.exists()
    assert str(expected_plist) in result.output
    assert f"launchctl load {expected_plist}" in result.output

    result_uninstall = runner.invoke(app, ["serve", "--uninstall-agent"])
    assert result_uninstall.exit_code == 0
    assert not expected_plist.exists()
    assert "LaunchAgent removed" in result_uninstall.output

    result_uninstall_again = runner.invoke(app, ["serve", "--uninstall-agent"])
    assert result_uninstall_again.exit_code == 0
    assert "No LaunchAgent installed" in result_uninstall_again.output


def test_plist_program_arguments_use_absolute_binary(tmp_path):
    with pytest.raises(AssertionError):
        render_plist(tmp_path, "merit", 4321)

    plist = render_plist(tmp_path, "/opt/homebrew/bin/merit", 4321)
    assert plist["ProgramArguments"][0] == "/opt/homebrew/bin/merit"


def _serve_option_names() -> set[str]:
    """Read the option names off the command itself. Asserting against --help
    text makes the check hostage to how rich decides to wrap and truncate the
    options panel, which varies with terminal width and interpreter (it passed
    locally and failed on CI, 2026-08-03)."""
    serve = typer.main.get_command(app).commands["serve"]
    return {name for param in serve.params for name in param.opts}


def test_serve_has_no_host_option():
    assert "--host" not in _serve_option_names()


def test_serve_help_shows_port_option():
    assert "--port" in _serve_option_names()


def test_serve_both_flags_errors():
    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--install-agent", "--uninstall-agent"])
    assert result.exit_code == 1
    assert "pass exactly one of --install-agent / --uninstall-agent" in result.output


def test_resolve_binary_raises_if_not_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    with pytest.raises(RuntimeError):
        resolve_binary()


def test_resolve_binary_returns_path_if_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/merit")
    assert resolve_binary() == "/usr/bin/merit"


def test_render_sync_plist_runs_ingest_hourly(tmp_path):
    plist = agent.render_sync_plist(
        tmp_path, python="/usr/bin/python3", workdir=tmp_path / "repo", interval=3600
    )

    assert plist["Label"] == agent.SYNC_LABEL
    assert plist["ProgramArguments"][0] == "/usr/bin/python3"
    assert plist["ProgramArguments"][-1] == "ingest-mail"
    assert plist["WorkingDirectory"] == str(tmp_path / "repo")
    assert plist["StartInterval"] == 3600
    # No credentials anywhere in the plist - keychain fallback handles auth.
    assert "MERIT_IMAP_PASSWORD" not in str(plist)


def test_render_sync_plist_chains_one_run_per_mailbox(tmp_path):
    plist = agent.render_sync_plist(
        tmp_path,
        python="/usr/bin/python3",
        workdir=tmp_path / "repo",
        mailboxes=("InMail", "Linkedin Jobs"),
    )

    assert plist["ProgramArguments"][0] == "/bin/sh"
    command = plist["ProgramArguments"][2]
    assert command.count("ingest-mail") == 2
    assert "--mailbox InMail" in command
    assert "--mailbox 'Linkedin Jobs'" in command
    assert "&&" in command
    assert "MERIT_IMAP_PASSWORD" not in command


def test_install_and_uninstall_sync_agent(tmp_path):
    written = agent.install_sync_agent(
        tmp_path, python="/usr/bin/python3", workdir=tmp_path / "repo"
    )

    assert written.exists()
    assert agent.SYNC_LABEL in written.name
    assert agent.uninstall_sync_agent(tmp_path) is True
    assert not written.exists()
    assert agent.uninstall_sync_agent(tmp_path) is False
