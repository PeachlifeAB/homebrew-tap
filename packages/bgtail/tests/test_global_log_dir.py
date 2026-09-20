"""Global-mode logs must not live in a world-writable shared directory.

/tmp/<basename> is predictable, so on a multi-user machine another user can
pre-create or symlink it and capture or corrupt the log, PID and exit files.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bgtail.cli import _log_dir


def test_global_logs_are_not_written_under_tmp() -> None:
    assert not str(_log_dir("global")).startswith("/tmp/")


def test_global_logs_honour_xdg_state_home(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))  # type: ignore[attr-defined]
    assert str(_log_dir("global")).startswith(str(tmp_path))


def test_global_logs_fall_back_to_local_state() -> None:
    os.environ.pop("XDG_STATE_HOME", None)
    assert ".local/state" in str(_log_dir("global"))
