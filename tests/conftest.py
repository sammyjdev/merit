# tests/conftest.py
import pytest

from merit import mail


@pytest.fixture(autouse=True)
def _isolate_merit_env(tmp_path_factory, monkeypatch):
    """Point the serve/env defaults at empty temp stores so no test ever
    scans the real corpus/ or ~/.merit (isolation + speed), and keep tests
    away from the real macOS keychain. Test fixtures that need data
    override these with their own monkeypatch."""
    base = tmp_path_factory.mktemp("merit-env")
    monkeypatch.setenv("MERIT_INBOX", str(base / "inbox"))
    monkeypatch.setenv("MERIT_QUEUE_PATH", str(base / "queue.json"))
    monkeypatch.setenv("MERIT_DB", str(base / "merit.db"))
    monkeypatch.setattr(mail, "_keychain", lambda service: None)
