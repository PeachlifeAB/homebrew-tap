from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ..domain.models import CommandFailed, ReleaseError

DISCOVERY_POLL_SECONDS = 2

# Bounds every command a release runs. Generous enough for `brew test` on a
# source build, short enough that a hung binary fails the release same-day.
DEFAULT_COMMAND_TIMEOUT_SECONDS = 900.0


def _timed_out(args: list[str], error: subprocess.TimeoutExpired) -> CommandFailed:
    return CommandFailed(f"{' '.join(args)} (no exit within {error.timeout:g}s)")


class SubprocessAdapter:
    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        capture: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        print("+", " ".join(args), flush=True)
        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                check=True,
                text=True,
                capture_output=capture,
                timeout=timeout_seconds or DEFAULT_COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise _timed_out(args, error) from error
        except subprocess.CalledProcessError as error:
            raise CommandFailed(" ".join(args)) from error
        return result.stdout.strip() if capture else ""

    def try_run(self, args: list[str], *, cwd: Path) -> tuple[int, str]:
        """Run a command tolerating a non-zero exit; return (returncode, stdout)."""
        print("+", " ".join(args), flush=True)
        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise _timed_out(args, error) from error
        return result.returncode, result.stdout

    def read_bytes(self, args: list[str], *, cwd: Path) -> bytes:
        print("+", " ".join(args), flush=True)
        try:
            return subprocess.run(
                args,
                cwd=cwd,
                check=True,
                capture_output=True,
                timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS,
            ).stdout
        except subprocess.TimeoutExpired as error:
            raise _timed_out(args, error) from error
        except subprocess.CalledProcessError as error:
            raise CommandFailed(" ".join(args)) from error

    def poll_until(
        self,
        args: list[str],
        *,
        cwd: Path,
        ready: Callable[[int, str], bool],
        attempts: int,
    ) -> str:
        """Re-run until `ready`, then return stdout; raise if it never is."""
        for _ in range(attempts):
            returncode, stdout = self.try_run(args, cwd=cwd)
            if ready(returncode, stdout):
                return stdout
            time.sleep(DISCOVERY_POLL_SECONDS)
        raise ReleaseError(f"timed out waiting for: {' '.join(args)}")


class LocalFileSystem:
    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def write_text(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()


class GitAdapter:
    def __init__(self, process: SubprocessAdapter) -> None:
        self.process = process

    def output(self, args: list[str], *, cwd: Path) -> str:
        return self.process.run(["git", *args], cwd=cwd, capture=True)

    def run(self, args: list[str], *, cwd: Path) -> None:
        self.process.run(["git", *args], cwd=cwd)


class GitHubAdapter:
    def __init__(self, process: SubprocessAdapter) -> None:
        self.process = process

    def release_exists(self, repository: str, tag: str) -> bool:
        code, _ = self.process.try_run(
            ["gh", "release", "view", tag, "--repo", repository], cwd=Path.cwd()
        )
        return code == 0

    def tag_commit(self, repository: str, tag: str) -> str | None:
        code, stdout = self.process.try_run(
            ["gh", "api", f"repos/{repository}/commits/{tag}", "--jq", ".sha"],
            cwd=Path.cwd(),
        )
        return stdout.strip() if code == 0 else None

    def create_release(
        self, repository: str, tag: str, asset: Path, title: str
    ) -> None:
        self.process.run(
            [
                "gh",
                "release",
                "create",
                tag,
                str(asset),
                "--repo",
                repository,
                "--title",
                title,
                "--notes",
                title,
            ],
            cwd=asset.parent,
        )

    def pull_request(self, repository: str, branch: str) -> tuple[int, str] | None:
        raw = self.process.run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repository,
                "--head",
                branch,
                "--state",
                "open",
                "--json",
                "number,headRefOid",
            ],
            cwd=Path.cwd(),
            capture=True,
        )
        rows = json.loads(raw)
        if not rows:
            return None
        return int(rows[0]["number"]), str(rows[0]["headRefOid"])


class SystemClock:
    def now_iso(self) -> str:
        return datetime.now(UTC).isoformat()


class Sha256Hasher:
    def sha256(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()


def command_available(command: str) -> bool:
    return (
        subprocess.run(
            ["/usr/bin/env", "which", command],
            capture_output=True,
            check=False,
            timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS,
        ).returncode
        == 0
    )


def require_commands(commands: tuple[str, ...]) -> None:
    missing = [command for command in commands if not command_available(command)]
    if missing:
        raise ReleaseError(f"required commands unavailable: {', '.join(missing)}")
