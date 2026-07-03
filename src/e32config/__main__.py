"""Console entry point: `e32config` or `python -m e32config`."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from e32config.app import run
    except ImportError as exc:  # pragma: no cover - dependency guard
        print(f"Missing dependency: {exc}\nInstall with: pip install e32config", file=sys.stderr)
        return 1
    run()
    return 0


def gui_main() -> int:
    try:
        from e32config.gui import run
    except ImportError as exc:  # pragma: no cover - dependency guard
        print(f"Missing dependency: {exc}\nInstall with: pip install e32config", file=sys.stderr)
        return 1
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
