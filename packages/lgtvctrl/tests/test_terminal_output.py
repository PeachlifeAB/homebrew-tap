"""A command prints its result, not the debug log: users read the terminal."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ENTRY = "import sys; from lgtvctrl.main import main; sys.exit(main(sys.argv[1:]))"


def _tv(args: list[str], home: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
    }
    return subprocess.run(
        [sys.executable, "-c", ENTRY, *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_version_prints_only_the_version(tmp_path: Path) -> None:
    result = _tv(["--version"], tmp_path)

    assert result.stdout.strip().startswith("tv ")
    assert result.stderr == ""


def test_a_command_result_reaches_the_terminal_as_plain_text(tmp_path: Path) -> None:
    """`tv screen off` reports its outcome through lgtvctrl's INFO log; a
    library's INFO line is noise to a user and stays in the log file."""
    script = (
        "import logging; from lgtvctrl.log import setup_logging; setup_logging(); "
        "logging.getLogger('lgtvctrl.screen').info('Screen off'); "
        "logging.getLogger('websockets.client').info('connection open')"
    )
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / ".config"),
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.stderr == "Screen off\n"


def test_debug_lines_still_reach_the_log_file(tmp_path: Path) -> None:
    _tv(["--version"], tmp_path)

    log = (tmp_path / ".config" / "lgtvctrl" / "lgtvctrl.log").read_text()
    assert "[DEBUG]" in log
