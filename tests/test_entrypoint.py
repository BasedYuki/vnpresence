"""Guards against the crash that shipped in v0.3.0's .exe.

PyInstaller runs the entry script standalone, without the package around it.
A relative import inside `__main__.py` works under `python -m vnpresence` but
dies as "attempted relative import with no known parent package" in the frozen
build. Running the files as plain scripts here reproduces exactly that context,
so the mistake cannot come back unnoticed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def run(script: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(SRC))
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_main_module_runs_as_a_plain_script():
    result = run(SRC / "vnpresence" / "__main__.py", "--help")
    assert "attempted relative import" not in result.stderr
    assert result.returncode == 0, result.stderr
    assert "VNPresence" in result.stdout


def test_pyinstaller_entry_script_runs():
    result = run(ROOT / "tools" / "entry.py", "--version")
    assert result.returncode == 0, result.stderr
    assert "vnpresence" in result.stdout.lower()


def test_module_invocation_still_works():
    env = dict(os.environ, PYTHONPATH=str(SRC))
    result = subprocess.run(
        [sys.executable, "-m", "vnpresence", "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
