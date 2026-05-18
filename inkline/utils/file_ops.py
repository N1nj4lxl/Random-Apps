from __future__ import annotations

import json
import shutil
from pathlib import Path


def read_text(path: str, encoding: str = "utf-8") -> str:
    return Path(path).read_text(encoding=encoding)


def write_text(path: str, text: str, encoding: str = "utf-8", endings: str = "LF") -> None:
    line_end = "\r\n" if endings == "CRLF" else "\n"
    normalized = "\n".join(text.splitlines())
    if text.endswith("\n"):
        normalized += "\n"
    Path(path).write_text(normalized.replace("\n", line_end), encoding=encoding)


def backup_file(path: str) -> str:
    src = Path(path)
    backup = src.with_suffix(src.suffix + ".bak")
    shutil.copy2(src, backup)
    return str(backup)


def export_file(path: str, text: str, export_type: str) -> None:
    p = Path(path)
    if export_type in {"TXT", "MD", "HTML"}:
        p.write_text(text, encoding="utf-8")
    elif export_type == "JSON":
        p.write_text(json.dumps({"content": text}, indent=2), encoding="utf-8")
    elif export_type == "PDF":
        p.write_bytes(("INKLINE PDF EXPORT\n\n" + text).encode("utf-8"))
