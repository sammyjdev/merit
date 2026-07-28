# tests/test_cli.py
from pathlib import Path

from typer.testing import CliRunner

from merit import cli
from merit.schemas import Demand, Demands, ResidueVerdicts
from tests.test_profile import FIXTURE

runner = CliRunner()


class FakeStructured:
    def __init__(self, result):
        self.result = result

    def invoke(self, prompt):
        return self.result


class FakeWriter:
    def invoke(self, prompt):
        class M:
            content = "- tailored bullet"

        return M()


def _patch_models(monkeypatch):
    monkeypatch.setattr(
        cli, "build_extractor",
        lambda: FakeStructured(
            Demands(demands=[Demand(name="FastAPI", kind="core", quote="FastAPI")])
        ),
    )
    monkeypatch.setattr(cli, "build_judge", lambda: FakeStructured(ResidueVerdicts(verdicts=[])))
    monkeypatch.setattr(cli, "build_writer", lambda: FakeWriter())


def test_match_then_approve_roundtrip(tmp_path, monkeypatch):
    _patch_models(monkeypatch)
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    posting = tmp_path / "vaga.md"
    posting.write_text("Senior role using FastAPI")

    r1 = runner.invoke(cli.app, ["match", str(posting), "--profile", str(FIXTURE)])
    assert r1.exit_code == 0, r1.output
    assert "# MERIT fit report" in r1.output and "Session: " in r1.output
    session_id = r1.output.split("Session: ")[1].split()[0]

    r2 = runner.invoke(cli.app, ["resume", session_id, "--approve", "--profile", str(FIXTURE)])
    assert r2.exit_code == 0, r2.output
    assert "- tailored bullet" in r2.output


def test_resume_rejects_on_profile_change(tmp_path, monkeypatch):
    _patch_models(monkeypatch)
    monkeypatch.setenv("MERIT_DB", str(tmp_path / "merit.db"))
    posting = tmp_path / "vaga.md"
    posting.write_text("Senior role using FastAPI")
    r1 = runner.invoke(cli.app, ["match", str(posting), "--profile", str(FIXTURE)])
    session_id = r1.output.split("Session: ")[1].split()[0]

    changed = tmp_path / "profile2.yaml"
    changed.write_text(Path(FIXTURE).read_text() + "\n# changed\n")
    r2 = runner.invoke(cli.app, ["resume", session_id, "--approve", "--profile", str(changed)])
    assert r2.exit_code == 2
    assert "profile changed" in r2.output
