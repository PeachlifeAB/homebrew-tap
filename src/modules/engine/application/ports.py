from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple, Protocol


class ProcessPort(Protocol):
    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        capture: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        """Run a command, failing if it exits non-zero or outlives its bound.

        A release runs binaries it has just built. Unbounded, a hung one stops
        the release forever rather than failing it, so the adapter bounds every
        call; pass `timeout_seconds` to widen it for a genuinely slow step.
        """
        ...

    def try_run(self, args: list[str], *, cwd: Path) -> tuple[int, str]:
        """Run tolerating a non-zero exit; return (returncode, stdout)."""
        ...

    def read_bytes(self, args: list[str], *, cwd: Path) -> bytes: ...

    def poll_until(
        self,
        args: list[str],
        *,
        cwd: Path,
        ready: Callable[[int, str], bool],
        attempts: int,
    ) -> str:
        """Re-run until `ready`, then return stdout; raise if it never is.

        Remote APIs give no push channel for resource registration, so the
        retry lives here at the I/O boundary rather than in a use case.
        """
        ...


class FileSystemPort(Protocol):
    def read_text(self, path: Path) -> str: ...

    def write_text(self, path: Path, content: str) -> None: ...

    def read_bytes(self, path: Path) -> bytes: ...


class GitPort(Protocol):
    def output(self, args: list[str], *, cwd: Path) -> str: ...

    def run(self, args: list[str], *, cwd: Path) -> None: ...


class GitHubPort(Protocol):
    def release_exists(self, repository: str, tag: str) -> bool: ...

    def tag_commit(self, repository: str, tag: str) -> str | None: ...

    def create_release(
        self, repository: str, tag: str, asset: Path, title: str
    ) -> None: ...

    def pull_request(self, repository: str, branch: str) -> tuple[int, str] | None: ...


class WorkflowPort(Protocol):
    def wait_for_pull_request(
        self, repository: str, branch: str
    ) -> tuple[int, str]: ...

    def publish(self, repository: str, pull_request: int, head_sha: str) -> None: ...


class HomebrewPort(Protocol):
    def update(self) -> None: ...

    def upgrade(self, formula: str) -> None: ...

    def test(self, formula: str) -> None: ...

    def prefix(self) -> Path: ...


class ClockPort(Protocol):
    def now_iso(self) -> str: ...


class HashPort(Protocol):
    def sha256(self, content: bytes) -> str: ...


class ReleasePorts(NamedTuple):
    """Every outbound port a release use case depends on."""

    process: ProcessPort
    git: GitPort
    github: GitHubPort
    hasher: HashPort
