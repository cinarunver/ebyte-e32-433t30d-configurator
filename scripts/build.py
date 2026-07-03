#!/usr/bin/env python3
"""Build standalone single-file binaries for both e32config front-ends.

Single source of truth for local builds and CI (.github/workflows/build.yml).

    python scripts/build.py            # build both (CLI + GUI)
    python scripts/build.py --only cli
    python scripts/build.py --only gui

Outputs land in ./dist. Requires the build extra: pip install -e .[build]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "e32config"


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def build_cli() -> None:
    """Console binary running the Textual TUI."""
    _run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--name", "e32config",
        str(SRC / "__main__.py"),
    ])


def build_gui() -> None:
    """Windowed binary running the CustomTkinter GUI.

    --windowed suppresses a stray console; --collect-all customtkinter bundles
    its theme/asset JSON so the compiled app starts (without it the GUI fails).
    """
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--windowed", "--name", "e32config-gui",
        "--collect-all", "customtkinter",
        str(SRC / "gui.py"),
    ]
    if sys.platform != "darwin":
        cmd.append("--onefile")
    _run(cmd)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=["cli", "gui"], help="build just one front-end")
    args = ap.parse_args()
    if args.only in (None, "cli"):
        build_cli()
    if args.only in (None, "gui"):
        build_gui()
    print("Binaries written to", ROOT / "dist", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
