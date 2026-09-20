from __future__ import annotations

import argparse
import os
import secrets
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import IO, Literal

from .debug import debug
from .terminal import (
    close_log_window,
    open_log_window,
)

LogMode = Literal["default", "project", "global"]
StdinPolicy = Literal["closed", "inherit"]

# The Literal members, named so comparisons read as the mode they test for.
LOG_DEFAULT: LogMode = "default"
LOG_PROJECT: LogMode = "project"
LOG_GLOBAL: LogMode = "global"
STDIN_CLOSED: StdinPolicy = "closed"
STDIN_INHERIT: StdinPolicy = "inherit"

KILL_COMMAND = "kill"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def format_version() -> str:
    """The installed distribution's version, which the formula asserts exactly.

    Deriving it from `git log` read whichever repository the user happened to
    be standing in, and stamped a development suffix onto every release build.
    """
    try:
        return f"bgtail {version('bgtail')}"
    except PackageNotFoundError:  # Source run without an installed distribution.
        return "bgtail 0+unknown"


def _caller_dir_basename() -> str:
    return Path.cwd().name


def _make_id() -> str:
    now = _utc_now()
    return f"{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}"


def _state_home() -> Path:
    """XDG_STATE_HOME, matching sive and lgtvctrl in this workspace.

    STATE rather than CACHE: the spec lists "actions history (logs, ...)" under
    state, and these logs are the product - a cache eviction would lose the
    output the tool exists to capture. Homebrew puts its own logs in CACHE, but
    those are disposable build output.

    Pid files live here too, not in XDG_RUNTIME_DIR: that is cleared at logout
    while `bgtail --reconnect <id>` must still find a job afterwards, and macOS
    does not define it. This matches how comparable tools ship in
    homebrew-core - watchman builds with WATCHMAN_USE_XDG_STATE_HOME=ON and
    herdr keeps its server state under XDG_STATE_HOME, both managing pid files
    and logs the same way.
    """
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))


def _log_dir(log_mode: LogMode) -> Path:
    if log_mode == LOG_GLOBAL:
        # Not /tmp: the name is predictable from the caller's directory, so on
        # a shared machine another user could pre-create or symlink it and
        # capture the log, pid and exit files written underneath.
        return _state_home() / "bgtail" / _caller_dir_basename()
    return Path.cwd() / "log" / "bgtail"


def _log_path(job_id: str, log_mode: LogMode) -> Path:
    return _log_dir(log_mode) / f"{job_id}.log"


def _state_dir(log_mode: LogMode) -> Path:
    return _log_dir(log_mode) / ".bgtail"


def _pid_path(job_id: str, log_mode: LogMode) -> Path:
    return _state_dir(log_mode) / f"{job_id}.pid"


def _exit_path(job_id: str, log_mode: LogMode) -> Path:
    return _state_dir(log_mode) / f"{job_id}.exit"


def _resolve_log_path(job_id: str, log_mode: LogMode) -> tuple[Path, LogMode]:
    # requirements.md: reconnect resolves LOG path for <ID>.
    if log_mode != LOG_DEFAULT:
        return _log_path(job_id, log_mode), log_mode

    default_path = _log_path(job_id, LOG_DEFAULT)
    if default_path.exists():
        return default_path, LOG_DEFAULT

    global_path = _log_path(job_id, LOG_GLOBAL)
    if global_path.exists():
        return global_path, LOG_GLOBAL

    return default_path, LOG_DEFAULT


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001
        return None


def _print_start_header(job_id: str, log_path: Path) -> None:
    print("bgtail will now run your command in background")
    print("and stream output to a log file.")
    print(f"ID: {job_id}")
    print(f"LOG: {log_path}")
    print("A dot will be added each 8 seconds as progress marker until completed.")
    print("To reconnect after timeout run:")
    print(f"bgtail --reconnect {job_id}")
    print("If anything hangs or for emergency cases use:")
    print(f"bgtail kill {job_id}")


def _print_reconnect_header(job_id: str, log_path: Path) -> None:
    print(f"Reconnecting to session {job_id}..")
    print()
    print(f"ID: {job_id}")
    print(f"LOG: {log_path}")
    print()
    print("To reconnect after timeout run:")
    print(f"bgtail --reconnect {job_id}")


def _print_footer(exit_code: int) -> None:
    print("IN PROGRESS: false")
    print(f"exit code {exit_code}")


def _wait_for_exit_file(job_id: str, log_mode: LogMode) -> int:
    exit_file = _exit_path(job_id, log_mode)

    while True:
        if exit_file.exists():
            code = _read_int(exit_file)
            if code is not None:
                return code
            return 1

        sys.stdout.write(".")
        sys.stdout.flush()
        time.sleep(8)


# The shell's conventional codes for a command that could not be run.
EXIT_NOT_EXECUTABLE = 126
EXIT_NOT_FOUND = 127


def _run_to_log(
    job_id: str,
    log_mode: LogMode,
    cmd_argv: list[str],
    stdin_policy: StdinPolicy,
    log_fh: IO[bytes],
) -> int:
    """Start the target with its output on log_fh and wait for it to finish."""
    try:
        proc = subprocess.Popen(
            cmd_argv,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=None if stdin_policy == STDIN_INHERIT else subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except FileNotFoundError as exc:
        debug(f"runner: command not found {cmd_argv!r}: {exc}")
        return EXIT_NOT_FOUND
    except PermissionError as exc:
        debug(f"runner: permission denied starting {cmd_argv!r}: {exc}")
        return EXIT_NOT_EXECUTABLE
    except OSError as exc:
        debug(f"runner: failed to start {cmd_argv!r}: {exc}")
        return 1

    _write_text_atomic(_pid_path(job_id, log_mode), f"{proc.pid}\n")
    return int(proc.wait())


def _runner(
    job_id: str,
    log_mode: LogMode,
    cmd_argv: list[str],
    stdin_policy: StdinPolicy = STDIN_CLOSED,
) -> int:
    log_path = _log_path(job_id, log_mode)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(log_path, "wb", buffering=0) as log_fh:
            exit_code = _run_to_log(job_id, log_mode, cmd_argv, stdin_policy, log_fh)
    except OSError as exc:
        debug(f"runner: failed to run {cmd_argv!r}: {exc}")
        exit_code = 1

    try:
        _write_text_atomic(_exit_path(job_id, log_mode), f"{exit_code}\n")
    except Exception as exc:  # noqa: BLE001
        debug(f"runner: failed to write exit file: {exc}")
    return exit_code


def _spawn_runner(
    job_id: str,
    log_mode: LogMode,
    cmd_argv: list[str],
    stdin_policy: StdinPolicy,
) -> None:
    runner_argv = [sys.executable, "-m", "bgtail.cli", f"--stdin={stdin_policy}"]
    if log_mode == LOG_PROJECT:
        runner_argv.append("--project-log")
    elif log_mode == LOG_GLOBAL:
        runner_argv.append("--global-log")

    runner_argv += ["--_runner", job_id, "--", *cmd_argv]

    subprocess.Popen(
        runner_argv,
        stdin=None if stdin_policy == STDIN_INHERIT else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def _resolve_pid_path(job_id: str) -> Path | None:
    """Find a job's PID file across caller directories, then project-log.

    Only this user's own state directory is searched. The previous version
    walked every /tmp subdirectory and trusted any .bgtail/<id>.pid it found,
    so another user on a shared machine could plant a PID file and have
    `bgtail kill` signal a process of their choosing.
    """
    candidates = (
        subdir / ".bgtail" / f"{job_id}.pid" for subdir in _caller_state_dirs()
    )
    found = next((path for path in candidates if path.exists()), None)
    if found is not None:
        return found

    # Fallback: project-log path
    pid_file = _pid_path(job_id, LOG_PROJECT)
    return pid_file if pid_file.exists() else None


def _caller_state_dirs() -> list[Path]:
    """Every caller directory under this user's bgtail state, if readable."""
    root = _state_home() / "bgtail"
    try:
        return [child for child in root.iterdir() if child.is_dir()]
    except OSError:
        return []


def _kill_job(job_id: str) -> int:
    pid_file = _resolve_pid_path(job_id)
    if pid_file is None:
        print(f"Error: Unknown session id: {job_id}", file=sys.stderr)
        return 1
    pid = _read_int(pid_file)
    if pid is None:
        print(f"Error: corrupt pid file for {job_id}", file=sys.stderr)
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"Process already dead (session {job_id})")
        return 0
    except PermissionError:
        print(f"Error: permission denied killing pid {pid}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    try:
        time.sleep(0.5)
        os.kill(pid, 0)
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except KeyboardInterrupt:
        return 130
    print(f"Killed session {job_id} (pid {pid})")
    return 0


_HELP = """bgtail - Run commands detached with minimal heartbeat

USAGE:
    bgtail <command> [args...]
    bgtail --project-log <command> [args...]
    bgtail --global-log <command> [args...]
    bgtail --no-log-popup <command> [args...]
    bgtail --stdin=inherit <command> [args...]
    bgtail --reconnect <ID>
    bgtail kill <ID>
    bgtail --version
    bgtail --help

--stdin=inherit passes the caller's stdin to the detached job.
The caller owns stdin; closing it delivers EOF to the target."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--version", action="store_true")
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument("--project-log", action="store_true")
    log_group.add_argument("--global-log", action="store_true")
    parser.add_argument("--reconnect")
    parser.add_argument("--no-log-popup", action="store_true")
    parser.add_argument(
        "--stdin", choices=("closed", "inherit"), default="closed", dest="stdin_policy"
    )
    parser.add_argument("--_runner", action="store_true")
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    return parser


def _strip_separator(argv: list[str]) -> list[str]:
    """Drop the `--` that separates bgtail's flags from the target command."""
    return argv[1:] if argv[:1] == ["--"] else argv


def _run_as_runner(
    ns: argparse.Namespace, log_mode: LogMode, stdin_policy: StdinPolicy
) -> int:
    if not ns.rest:
        return 1
    job_id = ns.rest[0]
    rest = _strip_separator(ns.rest[1:])
    if not rest:
        return 1
    return _runner(job_id, log_mode, rest, stdin_policy)


def _reconnect(job_id: str, log_mode: LogMode) -> int:
    """Reattach to a running or finished job and report its exit code."""
    log_path, resolved_log_mode = _resolve_log_path(job_id, log_mode)
    if not log_path.exists():
        print(f"Error: Unknown session id: {job_id}", file=sys.stderr)
        return 1

    _print_reconnect_header(job_id, log_path)

    exit_file = _exit_path(job_id, resolved_log_mode)
    if exit_file.exists():
        code = _read_int(exit_file)
        code = code if code is not None else 1
        print("DONE")
        _print_footer(code)
        return code

    code = _wait_for_exit_file(job_id, resolved_log_mode)
    sys.stdout.write("DONE\n")
    sys.stdout.flush()
    _print_footer(code)
    return code


def _launch(
    ns: argparse.Namespace, log_mode: LogMode, stdin_policy: StdinPolicy
) -> int:
    cmd_argv = _strip_separator(ns.rest)
    if not cmd_argv:
        print("Error: No command provided", file=sys.stderr)
        print("Run 'bgtail --help' for usage", file=sys.stderr)
        return 1

    job_id = _make_id()
    log_path = _log_path(job_id, log_mode)

    _spawn_runner(job_id, log_mode, cmd_argv, stdin_policy)

    window = open_log_window(
        log_path, exit_file=_exit_path(job_id, log_mode), no_window=ns.no_log_popup
    )
    _print_start_header(job_id, log_path)

    code = _wait_for_exit_file(job_id, log_mode)
    close_log_window(window)

    sys.stdout.write("DONE\n")
    sys.stdout.flush()
    _print_footer(code)
    return code


def _kill_command(argv: list[str]) -> int:
    job_id = argv[1] if len(argv) > 1 else None
    if job_id is None or job_id in ("-h", "--help"):
        print(f"Usage: bgtail {KILL_COMMAND} <ID>")
        return 1 if job_id is None else 0
    return _kill_job(job_id)


def _log_mode_of(ns: argparse.Namespace) -> LogMode:
    if ns.project_log:
        return LOG_PROJECT
    if ns.global_log:
        return LOG_GLOBAL
    return LOG_DEFAULT


def main(argv: list[str]) -> int:
    if argv and argv[0] == KILL_COMMAND:
        return _kill_command(argv)

    ns = _build_parser().parse_args(argv)

    if ns.version:
        print(format_version())
        return 0

    if ns.help:
        print(_HELP)
        return 0

    log_mode = _log_mode_of(ns)
    stdin_policy: StdinPolicy = ns.stdin_policy

    if ns._runner:
        return _run_as_runner(ns, log_mode, stdin_policy)

    if ns.reconnect:
        return _reconnect(ns.reconnect, log_mode)

    return _launch(ns, log_mode, stdin_policy)


def main_entry() -> None:
    raise SystemExit(main(sys.argv[1:]))


if __name__ == "__main__":
    main_entry()
