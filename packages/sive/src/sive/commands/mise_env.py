"""sive _mise-env — called by the mise Lua hook at shell startup.

Fast path: decrypt local tag snapshots only. No live bw calls, no network.
If a tag snapshot is missing or unreadable, warns once to stderr and skips it.
"""

from __future__ import annotations

import json
import os
import shlex
import sys

from ..core import ui
from ..core.project_config import active_tags
from ..core.snapshot import read_snapshot, snapshot_exists

# The hook sources this output; JSON stays the default for every other caller.
SHELL_FORMAT = "sh"


def run(tags: list[str], output_format: str = "json") -> int:
    """Emit merged snapshot env and never fail shell startup.

    The hook sources `--format=sh` directly. sive is already a Python
    process, so it quotes the values itself: inside `mise hook-env` PATH
    is led by mise's shim directory, and an interpreter resolved there
    re-enters mise and re-sources the hook, forking without bound.

    Contract:
      - stdout: JSON object, or `export k=v` lines when format is 'sh'
      - stderr: short warnings only
      - exit code: always 0
    """
    try:
        if not tags:
            tags = active_tags()

        vault_name = "personal"
        env: dict[str, str] = {}

        for tag in tags:
            if not snapshot_exists(vault_name, tag):
                _warn(
                    f"sive: no snapshot for tag '{tag}' — run 'sive setup' to populate"
                )
                continue
            result = read_snapshot(vault_name, tag)
            if result is None:
                _warn(
                    f"sive: could not read snapshot for tag '{tag}' — run 'sive setup'"
                )
                continue
            env.update(result)

        _emit(env, output_format)
        return 0
    except Exception as e:  # noqa: BLE001
        # The shell hook must never abort a shell start; it reports and exits.
        if os.getenv("SIVE_DEBUG"):
            _warn(f"sive: error reading snapshots — using empty env ({e})")
        else:
            _warn("sive: error reading snapshots — using empty env")
        _emit({}, output_format)
        return 0


def _emit(env: dict[str, str], output_format: str) -> None:
    if output_format == SHELL_FORMAT:
        for key, value in env.items():
            sys.stdout.write(f"export {key}={shlex.quote(str(value))}\n")
        return
    json.dump(env, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _warn(msg: str) -> None:
    ui.echo(msg, file=sys.stderr)
