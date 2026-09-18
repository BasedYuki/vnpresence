"""``python -m vnpresence`` and the frozen .exe entry point.

With no arguments it opens the window; with arguments it behaves as the CLI.

The imports here are absolute on purpose. A relative import (``from .gui``)
only works while this file is being run as part of the package, and PyInstaller
runs the entry script standalone - which crashed the first .exe with
"attempted relative import with no known parent package". Absolute imports work
in both worlds. `tests/test_entrypoint.py` runs this file as a plain script to
keep it that way.
"""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1:
        from vnpresence.cli import main as cli_main

        cli_main()
    else:
        from vnpresence.gui import run_gui

        run_gui()


if __name__ == "__main__":
    main()
