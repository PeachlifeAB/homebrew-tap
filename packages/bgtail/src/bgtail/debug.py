"""The debug log both the CLI and the terminal adapters write to.

Its own module so neither has to import the other.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def _utc_now() -> datetime:
    return datetime.now(UTC)


def debug_log_path() -> Path:
    # Always-on debug logs for traceability.
    return Path.cwd() / "log" / "bgtail" / "debug.log"


def debug(msg: str) -> None:
    ts = _utc_now().isoformat(timespec="milliseconds")
    path = debug_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{ts} {msg}\n")
