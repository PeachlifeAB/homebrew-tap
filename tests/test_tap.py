from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from release_engine.manifest import load_manifest
from release_engine.models import Handoff, ReleaseError
from release_engine.tap import TapRelease


class FakeProcess:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def read_bytes(self, args, *, cwd):
        return self.content


class FakeGitHub:
    def __init__(self, commit: str) -> None:
        self.commit = commit

    def tag_commit(self, repository, tag):
        return self.commit


class TapFormulaTests(unittest.TestCase):
    def test_update_formula_validates_handoff_and_removes_stale_bottle(self) -> None:
        source = b"source"
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            products = root / "release-products"
            products.mkdir()
            canonical = Path(__file__).resolve().parents[1]
            (products / "sive.toml").write_text(
                (canonical / "release-products" / "sive.toml").read_text()
            )
            formula_dir = root / "Formula"
            formula_dir.mkdir()
            formula = formula_dir / "sive.rb"
            formula.write_text(
                "class Sive < Formula\n"
                '  url "https://github.com/PeachlifeAB/sive/old.tar.gz"\n'
                f'  sha256 "{"0" * 64}"\n\n'
                '  bottle do\n    root_url "old"\n    sha256 arm64_tahoe: "old"\n  end\n\n'
                "  test do\n"
                '    assert_match version.to_s, shell_output("#{bin}/sive --version")\n'
                "  end\nend\n"
            )
            manifest = load_manifest(root, "sive")
            handoff = Handoff(
                1,
                "sive",
                manifest.repository,
                "0.1.8",
                "v0.1.8",
                commit,
                manifest.asset_url("0.1.8"),
                hashlib.sha256(source).hexdigest(),
            )
            release = TapRelease(
                root, manifest, FakeProcess(source), object(), FakeGitHub(commit)
            )
            release.update_formula(handoff)
            content = formula.read_text()

        self.assertIn(handoff.source_url, content)
        self.assertIn(handoff.source_sha256, content)
        self.assertNotIn("bottle do", content)

    def test_rejects_mismatched_product(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = load_manifest(root, "sive")
        handoff = Handoff(
            1,
            "bgtail",
            manifest.repository,
            "0.1.8",
            "v0.1.8",
            "a" * 40,
            manifest.asset_url("0.1.8"),
            "b" * 64,
        )
        release = TapRelease(
            root, manifest, FakeProcess(b""), object(), FakeGitHub("a" * 40)
        )
        with self.assertRaisesRegex(ReleaseError, "handoff mismatch"):
            release.validate_handoff(handoff)


if __name__ == "__main__":
    unittest.main()
