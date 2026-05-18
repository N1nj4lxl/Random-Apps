from __future__ import annotations
import json
from pathlib import Path


class WorkspaceManager:
    def __init__(self, workspace_file: str):
        self.path = Path(workspace_file)

    def load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
