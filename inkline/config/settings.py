from __future__ import annotations

import json
from pathlib import Path

SETTINGS_PATH = Path.home() / ".inkline_settings.json"
DEFAULTS = {
    "theme": "Dark",
    "accent": "#4f9cff",
    "font_family": "Consolas",
    "font_size": 12,
    "word_wrap": True,
    "autosave_seconds": 30,
    "always_on_top": False,
    "transparent": 1.0,
    "line_endings": "LF",
    "encoding": "utf-8",
    "search_history": [],
    "workspace_file": str(Path.home() / ".inkline_workspace.json"),
}


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return DEFAULTS | json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return DEFAULTS.copy()
    return DEFAULTS.copy()


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
