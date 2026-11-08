"""Filesystem locations that work both from source and inside a PyInstaller bundle."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "Takeoff"


def resource_dir() -> Path:
    """Read-only bundled resources (static/, rules/)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    """Per-user writable settings (user rules, recent projects)."""
    if env := os.environ.get("TAKEOFF_CONFIG"):
        p = Path(env)
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        p = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME.lower()
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_projects_dir() -> Path:
    docs = Path.home() / "Documents"
    p = (docs if docs.exists() else Path.home()) / f"{APP_NAME} Projects"
    p.mkdir(parents=True, exist_ok=True)
    return p


def user_rules_dir() -> Path:
    p = config_dir() / "rules"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---- recent projects --------------------------------------------------------
def _recent_file() -> Path:
    return config_dir() / "recent.json"


def recent_projects() -> list[str]:
    try:
        items = json.loads(_recent_file().read_text())
    except (OSError, ValueError):
        return []
    return [p for p in items if isinstance(p, str) and Path(p).exists()][:10]


def add_recent(path: str | Path) -> None:
    p = str(Path(path).resolve())
    items = [x for x in recent_projects() if x != p]
    try:
        _recent_file().write_text(json.dumps([p] + items[:9], indent=1))
    except OSError:
        pass
