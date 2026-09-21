from __future__ import annotations

import hashlib
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from modules.engine.application.ports import ProcessPort
from modules.engine.application.tap import TapRelease, source_url_pattern
from modules.engine.domain.models import Handoff, ReleaseError
from modules.engine.infrastructure.manifest import load_manifest


class FakeProcess:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        capture: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        return ""

    def try_run(self, args: list[str], *, cwd: Path) -> tuple[int, str]:
        return 0, ""

    def read_bytes(self, args: list[str], *, cwd: Path) -> bytes:
        return self.content

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
    """Never exercised by these tests; present to satisfy GitPort."""

    def run(self, args: list[str], *, cwd: Path) -> None:
        raise AssertionError("git should not be called")

    def output(self, args: list[str], *, cwd: Path) -> str:
        raise AssertionError("git should not be called")


class FakeGitHub:
    def __init__(self, commit: str) -> None:
        self.commit = commit

    def release_exists(self, repository: str, tag: str) -> bool:
        return True

    def tag_commit(self, repository: str, tag: str) -> str | None:
        return self.commit

    def create_release(
        self, repository: str, tag: str, asset: Path, title: str
    ) -> None:
        return None

    def pull_request(self, repository: str, branch: str) -> tuple[int, str] | None:
        return None


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
                '  url "https://github.com/PeachlifeAB/homebrew-tap/old.tar.gz"\n'
                f'  sha256 "{"0" * 64}"\n\n'
                '  bottle do\n    root_url "old"\n'
                '    sha256 arm64_tahoe: "old"\n  end\n\n'
                "  test do\n"
                '    assert_equal "sive #{version}", '
                'shell_output("#{bin}/sive --version").strip\n'
                "  end\nend\n"
            )
            manifest = load_manifest(root, "sive")
            handoff = Handoff(
                1,
                "sive",
                manifest.repository,
                "0.1.8",
                manifest.tag("0.1.8"),
                commit,
                manifest.asset_url("0.1.8"),
                hashlib.sha256(source).hexdigest(),
            )
            release = TapRelease(
                root, manifest, FakeProcess(source), FakeGit(), FakeGitHub(commit)
            )
            release.update_formula(handoff)
            content = formula.read_text()

        self.assertIn(handoff.source_url, content)
        self.assertIn(handoff.source_sha256, content)
        self.assertNotIn("bottle do", content)
        self.assertIn(f'  sha256 "{handoff.source_sha256}"\n\n  test do\n', content)

    def test_version_assertion_pattern_rejects_only_hardcoded_versions(
        self,
    ) -> None:
        """The check exists to refuse a hardcoded version, which passes against
        the previous release after a bump. It must not care which assertion
        spelling a formula uses — pinning one is how it broke."""
        from modules.engine.application.tap import version_assertion_pattern

        pattern = version_assertion_pattern("sive")
        accepted = (
            (
                '    assert_equal "sive #{version}", '
                'shell_output("#{bin}/sive --version").strip'
            ),
            '    assert_match version.to_s, shell_output("#{bin}/sive --version")',
        )
        for line in accepted:
            with self.subTest(accepted=line.strip()):
                self.assertRegex(line, pattern)

        rejected = (
            (
                '    assert_equal "sive 0.1.8", '
                'shell_output("#{bin}/sive --version").strip'
            ),
            (
                '    assert_equal "tv #{version}", '
                'shell_output("#{bin}/tv --version").strip'
            ),
        )
        for line in rejected:
            with self.subTest(rejected=line.strip()):
                self.assertNotRegex(line, pattern)

    def test_update_formula_accepts_every_shipped_formula(self) -> None:
        """The updater must accept the legacy URL during the first cutover.

        A release runs against the real `Formula/*.rb`, so keep the current
        shipped source URL shape in this fixture instead of replacing it with
        a synthetic URL owned by the new tap repository. The handoff still
        validates the new release asset before changing the formula.
        """
        canonical = Path(__file__).resolve().parents[1]
        for path in sorted((canonical / "release-products").glob("*.toml")):
            with self.subTest(product=path.stem):
                manifest = load_manifest(canonical, path.stem)
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    (root / "release-products").mkdir()
                    (root / "release-products" / path.name).write_text(path.read_text())
                    (root / "Formula").mkdir()
                    shipped = canonical / f"Formula/{manifest.formula}.rb"
                    content = shipped.read_text()
                    self.assertRegex(content, source_url_pattern())
                    (root / f"Formula/{manifest.formula}.rb").write_text(content)
                    handoff = Handoff(
                        1,
                        manifest.name,
                        manifest.repository,
                        "9.9.9",
                        manifest.tag("9.9.9"),
                        "a" * 40,
                        manifest.asset_url("9.9.9"),
                        hashlib.sha256(b"source").hexdigest(),
                    )
                    release = TapRelease(
                        root,
                        manifest,
                        FakeProcess(b"source"),
                        FakeGit(),
                        FakeGitHub("a" * 40),
                    )
                    release.update_formula(handoff)

    def test_rejects_mismatched_product(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = load_manifest(root, "sive")
        handoff = Handoff(
            1,
            "bgtail",
            manifest.repository,
            "0.1.8",
            "sive-v0.1.8",
            "a" * 40,
            manifest.asset_url("0.1.8"),
            "b" * 64,
        )
        release = TapRelease(
            root, manifest, FakeProcess(b""), FakeGit(), FakeGitHub("a" * 40)
        )
        with self.assertRaisesRegex(ReleaseError, "handoff mismatch"):
            release.validate_handoff(handoff)


class WaitForChecksTests(unittest.TestCase):
    """Discovery polling belongs in infrastructure, behind ProcessPort."""

    def _release(self, process: ProcessPort) -> TapRelease:
        root = Path(__file__).resolve().parents[1]
        manifest = load_manifest(root, "sive")
        return TapRelease(root, manifest, process, FakeGit(), FakeGitHub("a" * 40))

    def test_application_layer_does_not_sleep(self) -> None:
        source = Path("src/modules/engine/application/tap.py").read_text()
        self.assertNotIn(
            "time.sleep",
            source,
            "retry/backoff belongs in infrastructure/adapters.py, not application/",
        )

    def test_check_discovery_does_not_request_unused_fields(self) -> None:
        """--json name,state was requested but state was never read."""
        calls: list[list[str]] = []

        class RecordingProcess(FakeProcess):
            def try_run(self, args: list[str], *, cwd: Path) -> tuple[int, str]:
                calls.append(args)
                return 0, '[{"name": "bottle"}]'

        self._release(RecordingProcess(b""))._wait_for_checks(1)
        self.assertTrue(calls, "expected a discovery call")
        self.assertNotIn(
            "name,state",
            " ".join(calls[0]),
            "state is never read; requesting it implies a guarantee not provided",
        )


if __name__ == "__main__":
    unittest.main()
