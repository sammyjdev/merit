"""LaunchAgent module for managing merit serve background service on macOS."""

import plistlib
import shutil
from pathlib import Path

LABEL = "com.sammyjdev.merit-serve"


def plist_path(home: Path) -> Path:
    """Return home / Library / LaunchAgents / {LABEL}.plist"""
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path(home: Path) -> Path:
    """Return home / .merit / serve.log"""
    return home / ".merit" / "serve.log"


def render_plist(home: Path, binary: str, port: int) -> dict:
    """Return the LaunchAgent plist configuration as a plain dict."""
    assert Path(binary).is_absolute(), f"Binary path must be absolute: {binary}"  # noqa: S101
    return {
        "Label": LABEL,
        "ProgramArguments": [binary, "serve", "--port", str(port)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_path(home)),
        "StandardErrorPath": str(log_path(home)),
    }


def resolve_binary() -> str:
    """Resolve absolute path to merit binary via shutil.which."""
    binary = shutil.which("merit")
    if not binary:
        raise RuntimeError("merit binary not found on PATH")
    return binary


def install_agent(home: Path, binary: str, port: int) -> Path:
    """Install the LaunchAgent plist file to plist_path(home)."""
    p = plist_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    log_path(home).parent.mkdir(parents=True, exist_ok=True)
    plist_data = render_plist(home, binary, port)
    with open(p, "wb") as f:
        plistlib.dump(plist_data, f)
    return p


def uninstall_agent(home: Path) -> bool:
    """Uninstall the LaunchAgent plist file if present."""
    p = plist_path(home)
    if p.exists():
        p.unlink()
        return True
    return False


SYNC_LABEL = "com.sammyjdev.merit-sync"


def sync_plist_path(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{SYNC_LABEL}.plist"


def sync_log_path(home: Path) -> Path:
    return home / ".merit" / "sync.log"


def render_sync_plist(home: Path, python: str, workdir: Path, interval: int = 3600) -> dict:
    """Hourly ingest-mail job. Credentials never enter the plist: the mail
    module falls back to the keychain (merit-imap-user / merit-imap-pass)."""
    assert Path(python).is_absolute(), f"Python path must be absolute: {python}"  # noqa: S101
    return {
        "Label": SYNC_LABEL,
        "ProgramArguments": [python, "-c", "from merit.cli import app; app()", "ingest-mail"],
        "WorkingDirectory": str(workdir),
        "StartInterval": interval,
        "RunAtLoad": True,
        "StandardOutPath": str(sync_log_path(home)),
        "StandardErrorPath": str(sync_log_path(home)),
    }


def install_sync_agent(home: Path, python: str, workdir: Path, interval: int = 3600) -> Path:
    p = sync_plist_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    sync_log_path(home).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        plistlib.dump(render_sync_plist(home, python, workdir, interval), f)
    return p


def uninstall_sync_agent(home: Path) -> bool:
    p = sync_plist_path(home)
    if p.exists():
        p.unlink()
        return True
    return False
