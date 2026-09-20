from __future__ import annotations

import hashlib
import io
import os
import tarfile
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from modules.engine.application.ports import ReleasePorts
from modules.engine.application.producer import ProducerRelease
from modules.engine.domain.models import (
    ReleaseError,
    ReleaseObservation,
    RepositoryState,
)
from modules.engine.infrastructure.manifest import load_manifest


class FakeProcess:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        capture: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        self.commands.append(args)
        return "sive 0.1.8" if capture else ""

    def try_run(self, args: list[str], *, cwd: Path) -> tuple[int, str]:
        self.commands.append(args)
        return 0, ""

    def read_bytes(self, args: list[str], *, cwd: Path) -> bytes:
        self.commands.append(args)
        return b""

    def poll_until(
        self,
        args: list[str],
        *,
        cwd: Path,
        ready: Callable[[int, str], bool],
        attempts: int,
    ) -> str:
        code, out = self.try_run(args, cwd=cwd)
        if not ready(code, out):
            raise AssertionError(f"not ready on first attempt: {args}")
        return out


class FakeGit:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.outputs = ["c" * 40, "c" * 40]

    def run(self, args: list[str], *, cwd: Path) -> None:
        self.commands.append(args)

    def output(self, args: list[str], *, cwd: Path) -> str:
        self.commands.append(args)
        return self.outputs.pop(0)


class FakeGitHub:
    def release_exists(self, repository: str, tag: str) -> bool:
        return False

    def tag_commit(self, repository: str, tag: str) -> str | None:
        return None

    def create_release(
        self, repository: str, tag: str, asset: Path, title: str
    ) -> None:
        return None

    def pull_request(self, repository: str, branch: str) -> tuple[int, str] | None:
        return None


class FakeHasher:
    def sha256(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()


class ProducerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tap_root = Path(__file__).resolve().parents[1]
        self.manifest = load_manifest(self.tap_root, "sive")

    def test_prepare_dry_run_does_not_write(self) -> None:
        process = FakeProcess()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observation = ReleaseObservation(
                self.manifest,
                RepositoryState("main", "a" * 40, "origin/main", 0, 0, ()),
                "0.1.7",
                "0.1.7",
                None,
                None,
                False,
            )
            release = ProducerRelease(
                self.manifest,
                root,
                ReleasePorts(process, FakeGit(), FakeGitHub(), FakeHasher()),
            )
            with patch.object(release, "observe", return_value=observation):
                release.prepare("0.1.8", dry_run=True)

            self.assertEqual(process.commands, [])
            self.assertFalse((root / "pyproject.toml").exists())

    def test_commit_precedes_tag_and_joint_push(self) -> None:
        process = FakeProcess()
        git = FakeGit()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "sive"\nversion = "0.1.8"\n'
            )
            (root / "uv.lock").write_text(
                '[[package]]\nname = "sive"\nversion = "0.1.8"\n'
            )
            release = ProducerRelease(
                self.manifest,
                root,
                ReleasePorts(process, git, FakeGitHub(), FakeHasher()),
            )
            release.commit_tag_push("0.1.8", dry_run=False)

        tag = self.manifest.tag("0.1.8")
        commit_index = git.commands.index(["commit", "-m", "release: prepare 0.1.8"])
        tag_index = git.commands.index(["tag", "-a", tag, "-m", "Release 0.1.8"])
        self.assertLess(commit_index, tag_index)
        self.assertIn(["push", "origin", "main", tag], git.commands)

    def test_commit_stages_the_workspace_lockfile(self) -> None:
        """The single lock lives at the workspace root, not beside the package."""
        process = FakeProcess()
        git = FakeGit()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "uv.lock").write_text(
                '[[package]]\nname = "sive"\nversion = "0.1.8"\n'
            )
            member = workspace / "packages" / "sive"
            member.mkdir(parents=True)
            (member / "pyproject.toml").write_text(
                '[project]\nname = "sive"\nversion = "0.1.8"\n'
            )
            release = ProducerRelease(
                self.manifest,
                member,
                ReleasePorts(process, git, FakeGitHub(), FakeHasher()),
            )
            release.commit_tag_push("0.1.8", dry_run=False)

        expected_lock = os.path.relpath(workspace / "uv.lock", member)
        self.assertIn(["add", "pyproject.toml", expected_lock], git.commands)

    def test_sdist_rejects_symlink_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / "sive-0.1.8.tar.gz"
            with tarfile.open(asset, "w:gz") as archive:
                pyproject = b'[project]\nname = "sive"\nversion = "0.1.8"\n'
                info = tarfile.TarInfo("sive-0.1.8/pyproject.toml")
                info.size = len(pyproject)
                archive.addfile(info, io.BytesIO(pyproject))
                symlink = tarfile.TarInfo("sive-0.1.8/CLAUDE.md")
                symlink.type = tarfile.SYMTYPE
                symlink.linkname = "/private/agent/CLAUDE.md"
                archive.addfile(symlink)
            release = ProducerRelease(
                self.manifest,
                root,
                ReleasePorts(FakeProcess(), FakeGit(), FakeGitHub(), FakeHasher()),
            )

            with self.assertRaisesRegex(ReleaseError, "unsafe members"):
                release._verify_sdist(asset, "0.1.8")

    def test_build_release_pins_the_sdist_output_to_the_package(self) -> None:
        """uv builds at the workspace root; the engine reads the package dist/."""
        process = FakeProcess()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = ProducerRelease(
                self.manifest,
                root,
                ReleasePorts(process, FakeGit(), FakeGitHub(), FakeHasher()),
            )
            with self.assertRaises(ReleaseError):
                release.build_release("0.1.8", "c" * 40, dry_run=False)

        self.assertIn(
            ["uv", "build", "--sdist", "--out-dir", str(root.resolve() / "dist")],
            process.commands,
        )


if __name__ == "__main__":
    unittest.main()
