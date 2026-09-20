"""Open and close the window that tails a job's log.

Two platforms, two mechanisms: macOS drives Terminal.app through osascript and
gets back a window id it can close later; Linux spawns the terminal Debian's
alternatives system names and cannot address the window afterwards, so closing
is a no-op there — the emulator exits when its `tail` does.

Where neither exists the window is skipped and the job still runs, which is the
behaviour a headless machine wants.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .debug import debug

# The Debian alternatives name every desktop terminal registers under. Checked
# before the concrete emulators so a configured preference wins.
# The osascript window-info call returns
# "existingWindowCount|createdWindowId|createdTTY" on stdout.
WINDOW_INFO_SEPARATORS = 2

LINUX_TERMINALS = (
    "x-terminal-emulator",
    "gnome-terminal",
    "konsole",
    "xfce4-terminal",
    "alacritty",
    "foot",
    "xterm",
)


@dataclass(frozen=True)
class TerminalWindow:
    window_id: str
    tty: str
    quit_if_empty: bool


def should_open_window(no_window_flag: bool = False) -> bool:
    if no_window_flag:
        return False

    if os.environ.get("NO_WINDOW"):
        return False

    for key in ("SSH_CLIENT", "SSH_TTY", "SSH_CONNECTION"):
        if os.environ.get(key):
            return False

    return True


def _macos_shell_command(command: str) -> str:
    return f"exec /bin/zsh -lc {shlex.quote(command)}"


def _open_macos(
    log_path: Path,
    exit_file: Path | None = None,
    *,
    no_window: bool = False,
) -> TerminalWindow | None:
    if not should_open_window(no_window):
        return None

    if exit_file is not None:
        tail_cmd = (
            f"tail -f {shlex.quote(str(log_path))} & TAIL_PID=$!; "
            f"while [ ! -f {shlex.quote(str(exit_file))} ]; do sleep 1; done; "
            f"sleep 2; kill $TAIL_PID 2>/dev/null; exit"
        )
    else:
        tail_cmd = f"exec tail -f {shlex.quote(str(log_path))}"

    terminal_cmd = _macos_shell_command(tail_cmd)

    try:
        proc = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Terminal" to launch',
                "-e",
                'tell application "Terminal" to set existingWindowCount to count of windows',
                "-e",
                'tell application "Terminal" to set createdTab to do script ""',
                "-e",
                "delay 1",
                "-e",
                f'tell application "Terminal" to do script {json.dumps(terminal_cmd)} in createdTab',
                "-e",
                'tell application "Terminal" to set createdWindowId to id of (first window whose tabs contains createdTab)',
                "-e",
                'tell application "Terminal" to set createdTTY to tty of createdTab',
                "-e",
                'tell application "Terminal" to activate',
                "-e",
                'return (existingWindowCount as text) & "|" & (createdWindowId as text) & "|" & createdTTY',
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        debug("terminal: osascript not found; skipping window")
        return None

    if proc.returncode != 0:
        debug(
            f"terminal: failed to open log window; stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
        return None

    output = proc.stdout.strip()
    if output.count("|") != WINDOW_INFO_SEPARATORS:
        debug(
            f"terminal: failed to parse window info; stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
        return None

    existing_window_count_text, window_id, tty = output.split("|", 2)
    existing_window_count_text = existing_window_count_text.strip()
    window_id = window_id.strip()
    tty = tty.strip()
    if not existing_window_count_text or not window_id or not tty:
        debug(
            f"terminal: incomplete window info; stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
        return None

    try:
        existing_window_count = int(existing_window_count_text)
    except ValueError:
        debug(f"terminal: invalid existing window count {existing_window_count_text!r}")
        return None

    return TerminalWindow(
        window_id=window_id,
        tty=tty,
        quit_if_empty=(existing_window_count == 0),
    )


def _close_macos(window: TerminalWindow | None) -> None:
    if not window:
        return

    try:
        window_id = int(window.window_id)
    except ValueError:
        debug(f"terminal: invalid window id {window.window_id!r}")
        return

    try:
        proc = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Terminal" to activate',
                "-e",
                f'tell application "Terminal" to if (count of (every window whose id is {window_id})) > 0 then set frontmost of window id {window_id} to true',
                "-e",
                'tell application "System Events" to tell process "Terminal" to click button 1 of front window',
                "-e",
                "delay 0.5",
                "-e",
                'tell application "System Events" to tell process "Terminal" to if exists (first sheet of front window) then click button "Terminate" of first sheet of front window',
                "-e",
                "delay 0.5",
                "-e",
                f'tell application "Terminal" to if {str(window.quit_if_empty).lower()} and (count of windows) is 0 then quit',
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return

    if proc.returncode != 0:
        debug(
            f"terminal: failed to close window {window_id}; stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )


def _linux_shell_command(command: str) -> str:
    """`/bin/sh` is the one shell a Linux image is guaranteed to have.

    The macOS path hardcodes `/bin/zsh`, which is absent from a plain Debian.
    """
    return f"exec /bin/sh -lc {shlex.quote(command)}"


def _linux_terminal() -> str | None:
    for candidate in LINUX_TERMINALS:
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _open_linux(log_path: Path, exit_file: Path | None) -> TerminalWindow | None:
    """Spawn a terminal tailing the log, detached from this process."""
    terminal = _linux_terminal()
    if terminal is None:
        debug("terminal: no terminal emulator found; skipping window")
        return None

    if exit_file is not None:
        tail_cmd = (
            f"tail -f {shlex.quote(str(log_path))} & TAIL_PID=$!; "
            f"while [ ! -f {shlex.quote(str(exit_file))} ]; do sleep 1; done; "
            f"sleep 2; kill $TAIL_PID 2>/dev/null; exit"
        )
    else:
        tail_cmd = f"exec tail -f {shlex.quote(str(log_path))}"

    try:
        process = subprocess.Popen(
            [terminal, "-e", _linux_shell_command(tail_cmd)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        debug(f"terminal: failed to spawn {terminal}: {error}")
        return None

    # The emulator owns the window; it exits when its tail does, so there is
    # nothing to close and no id to close it by.
    return TerminalWindow(window_id=str(process.pid), tty="", quit_if_empty=False)


def open_log_window(
    log_path: Path, *, exit_file: Path | None = None, no_window: bool = False
) -> TerminalWindow | None:
    """Open a window tailing the log, or None when the platform offers none."""
    if not should_open_window(no_window):
        return None

    if shutil.which("osascript"):
        return _open_macos(log_path, exit_file=exit_file, no_window=no_window)
    return _open_linux(log_path, exit_file)


def close_log_window(window: TerminalWindow | None) -> None:
    """Close a window this module opened; a no-op where it cannot be addressed."""
    if window is None or not window.tty:
        return
    _close_macos(window)
