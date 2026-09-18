"""``python -m vnpresence`` and the frozen .exe entry point.

With no arguments it opens the window; with arguments it behaves as the CLI.
"""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1:
        from .cli import main as cli_main

        cli_main()
    else:
        from .gui import run_gui

        run_gui()


if __name__ == "__main__":
    main()
