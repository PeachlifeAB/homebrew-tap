from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release_engine.manifest import load_manifest
from release_engine.models import ReleaseError, ReleaseObservation, RepositoryState
from release_engine.producer import ProducerRelease


class FakeProcess:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args, *, cwd, capture=False):
        self.commands.append(args)
        return "sive 0.1.8" if capture else ""


class FakeGit:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.outputs = ["c" * 40, "c" * 40]

    def run(self, args, *, cwd):
        self.commands.append(args)

    def output(self, args, *, cwd):
        self.commands.append(args)
        return self.outputs.pop(0)


class FakeGitHub:
    def release_exists(self, repository, tag):
        return False

    def tag_commit(self, repository, tag):
        return None


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
                self.manifest, root, process, FakeGit(), FakeGitHub()
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
            release = ProducerRelease(self.manifest, root, process, git, FakeGitHub())
            release.commit_tag_push("0.1.8", dry_run=False)

        commit_index = git.commands.index(["commit", "-m", "release: prepare 0.1.8"])
        tag_index = git.commands.index(["tag", "-a", "v0.1.8", "-m", "Release 0.1.8"])
        self.assertLess(commit_index, tag_index)
        self.assertIn(["push", "origin", "main", "v0.1.8"], git.commands)

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
                self.manifest, root, FakeProcess(), FakeGit(), FakeGitHub()
            )

            with self.assertRaisesRegex(ReleaseError, "unsafe members"):
                release._verify_sdist(asset, "0.1.8")


if __name__ == "__main__":
    unittest.main()
