from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .models import ReleaseError


class SubprocessAdapter:
    def run(self, args: list[str], *, cwd: Path, capture: bool = False) -> str:
        print("+", " ".join(args), flush=True)
        result = subprocess.run(
            args,
            cwd=cwd,
            check=True,
            text=True,
            capture_output=capture,
        )
        return result.stdout.strip() if capture else ""

    def read_bytes(self, args: list[str], *, cwd: Path) -> bytes:
        print("+", " ".join(args), flush=True)
        return subprocess.run(args, cwd=cwd, check=True, capture_output=True).stdout


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
        result = subprocess.run(
            ["gh", "release", "view", tag, "--repo", repository],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def tag_commit(self, repository: str, tag: str) -> str | None:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repository}/commits/{tag}",
                "--jq",
                ".sha",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None

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
            ["/usr/bin/env", "which", command], capture_output=True, check=False
        ).returncode
        == 0
    )


def require_commands(commands: tuple[str, ...]) -> None:
    missing = [command for command in commands if not command_available(command)]
    if missing:
        raise ReleaseError(f"required commands unavailable: {', '.join(missing)}")
