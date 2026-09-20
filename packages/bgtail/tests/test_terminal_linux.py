"""The Linux adapter, exercised on Linux.

Patching `subprocess.run` and asserting on the argv proves the command is
well-formed, never that it works: the macOS tests do exactly that, and would
pass unchanged against the `/bin/zsh` Debian does not have. This runs the real
adapter in a container, and skips where Docker is absent.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
IMAGE = "debian:stable-slim"

SCRIPT = """
set -e
apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq python3 python3-pip xterm >/dev/null 2>&1
cp -r /pkg /work && cd /work
pip install -q --break-system-packages . >/dev/null 2>&1

cd /tmp && mkdir -p with && cd with
python3 -c "
from pathlib import Path
from bgtail.terminal import _linux_shell_command, close_log_window, open_log_window
log = Path('job.log'); log.write_text('hello')
window = open_log_window(log)
assert window is not None, 'a terminal is installed; the window must open'
close_log_window(window)
assert _linux_shell_command('x').startswith('exec /bin/sh'), 'zsh is macOS-only'
print('SPAWNED')
"

rm -f /usr/bin/x-terminal-emulator /etc/alternatives/x-terminal-emulator /usr/bin/xterm
cd /tmp && mkdir -p without && cd without
python3 -c "
from pathlib import Path
from bgtail.terminal import open_log_window
log = Path('job.log'); log.write_text('hello')
assert open_log_window(log) is None, 'no terminal: the window must be skipped'
print('SKIPPED')
"

cd /tmp && mkdir -p job && cd job
bgtail --project-log echo linux-adapter-proof >/dev/null 2>&1
find . -name '*.log' ! -name debug.log -exec cat {} +
"""


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    probe = subprocess.run(["docker", "info"], capture_output=True, check=False)
    return probe.returncode == 0


@pytest.mark.skipif(not _docker_available(), reason="Docker is not available")
def test_linux_adapter_spawns_skips_and_runs_a_job() -> None:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{PACKAGE}:/pkg:ro",
            IMAGE,
            "bash",
            "-c",
            SCRIPT,
        ],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "SPAWNED" in result.stdout, result.stdout
    assert "SKIPPED" in result.stdout, result.stdout
    assert "linux-adapter-proof" in result.stdout, result.stdout
