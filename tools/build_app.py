from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = PROJECT_ROOT / "inkline" / "main.py"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"

def _ensure_pyinstaller() -> None:
    if shutil.which("pyinstaller"):
        return
    raise SystemExit(
        "PyInstaller is not installed. Install it with: python -m pip install pyinstaller"
    )


def build(one_file: bool = False, clean: bool = True) -> None:
    _ensure_pyinstaller()

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name",
        "Inkline",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(PROJECT_ROOT),
        str(ENTRYPOINT),
    ]

    if one_file:
        cmd.insert(4, "--onefile")

    if clean:
        cmd.insert(4, "--clean")

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)

    target = DIST_DIR / ("Inkline.exe" if one_file else "Inkline")
    print(f"Build complete: {target}")


if __name__ == "__main__":
    onefile = "--onefile" in sys.argv
    noclean = "--no-clean" in sys.argv
    build(one_file=onefile, clean=not noclean)
