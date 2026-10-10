from __future__ import annotations

import hashlib
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from modules.engine.application.ports import ProcessPort
from modules.engine.application.tap import (
    TAP_PYTHON_FILE,
    TapRelease,
    source_url_pattern,
)
from modules.engine.domain.models import Handoff, ProductManifest, ReleaseError
from modules.engine.infrastructure.manifest import load_manifest, load_product


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
        self, repository: str, tag: str, asset: Path, title: str, notes: str
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

    def test_a_release_moves_the_formula_to_the_tap_python(self) -> None:
        """The release PR rebuilds the bottle, so it is where a formula moves to
        the Python the tap ships and tests on; changing it anywhere else leaves
        a bottle built on the old one."""
        source = b"source"
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = Path(__file__).resolve().parents[1]
            (root / "release-products").mkdir()
            (root / "release-products" / "sive.toml").write_text(
                (canonical / "release-products" / "sive.toml").read_text()
            )
            (root / TAP_PYTHON_FILE).write_text("3.14\n")
            (root / "Formula").mkdir()
            formula = root / "Formula" / "sive.rb"
            formula.write_text(
                "class Sive < Formula\n"
                '  url "https://github.com/PeachlifeAB/homebrew-tap/old.tar.gz"\n'
                f'  sha256 "{"0" * 64}"\n\n'
                '  depends_on "python@3.13"\n\n'
                "  def install\n"
                '    venv = virtualenv_create(libexec, "python3.13")\n'
                "  end\n\n"
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
            TapRelease(
                root,
                manifest,
                FakeProcess(source),
                FakeGit(),
                FakeGitHub(commit),
            ).update_formula(handoff)
            content = formula.read_text()

        self.assertIn('depends_on "python@3.14"', content)
        self.assertIn('virtualenv_create(libexec, "python3.14")', content)
        self.assertNotIn("3.13", content)

    def test_post_verify_uses_executable_as_version_label(self) -> None:
        class VersionProcess(FakeProcess):
            def run(
                self,
                args: list[str],
                *,
                cwd: Path,
                capture: bool = False,
                timeout_seconds: float | None = None,
            ) -> str:
                if args == ["brew", "--prefix"]:
                    return "/tmp"
                if capture:
                    return "tv 0.1.1"
                return ""

        root = Path(__file__).resolve().parents[1]
        manifest = load_manifest(root, "lgtvctrl")
        release = TapRelease(
            root, manifest, VersionProcess(b""), FakeGit(), FakeGitHub("a" * 40)
        )
        release.post_verify("0.1.1", root)

    def _post_verify_commands(self, *, installed: bool) -> list[list[str]]:
        """Every command post-verify issues for sive on a machine where brew
        does (or does not) already have the formula."""

        class BrewProcess(FakeProcess):
            def __init__(self) -> None:
                super().__init__(b"")
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
                if args == ["brew", "--prefix"]:
                    return "/tmp"
                return "sive 0.1.10" if capture else ""

            def try_run(self, args: list[str], *, cwd: Path) -> tuple[int, str]:
                self.commands.append(args)
                return (0, "sive 0.1.9") if installed else (1, "")

        root = Path(__file__).resolve().parents[1]
        process = BrewProcess()
        release = TapRelease(
            root,
            load_manifest(root, "sive"),
            process,
            FakeGit(),
            FakeGitHub("a" * 40),
        )
        release.post_verify("0.1.10", root)
        return process.commands

    def test_post_verify_installs_a_formula_brew_does_not_have(self) -> None:
        commands = self._post_verify_commands(installed=False)

        self.assertIn(["brew", "install", "peachlifeab/tap/sive"], commands)
        self.assertNotIn(["brew", "upgrade", "sive"], commands)

    def test_post_verify_upgrades_a_formula_brew_already_has(self) -> None:
        commands = self._post_verify_commands(installed=True)

        self.assertIn(["brew", "upgrade", "sive"], commands)
        self.assertNotIn(["brew", "install", "peachlifeab/tap/sive"], commands)

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
        formula_manifests = (
            path
            for path in sorted((canonical / "release-products").glob("*.toml"))
            if isinstance(load_product(canonical, path.stem), ProductManifest)
        )
        for path in formula_manifests:
            with self.subTest(product=path.stem):
                manifest = load_manifest(canonical, path.stem)
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    (root / "release-products").mkdir()
                    (root / "release-products" / path.name).write_text(path.read_text())
                    (root / "Formula").mkdir()
                    (root / TAP_PYTHON_FILE).write_text("3.14\n")
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
                    released = (root / f"Formula/{manifest.formula}.rb").read_text()
                    self.assertIn('depends_on "python@3.14"', released)
                    self.assertIn('virtualenv_create(libexec, "python3.14")', released)

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


class BottleBeforePublishTests(unittest.TestCase):
    """brew test-bot marks a failing formula SKIPPED and still exits 0, so green
    checks do not mean a bottle exists; publishing then fails at brew pr-pull."""

    HEAD = "b" * 40

    def _publish(self, artifact_names: str) -> list[list[str]]:
        calls: list[list[str]] = []
        head = self.HEAD

        class PullRequestProcess(FakeProcess):
            def run(
                self,
                args: list[str],
                *,
                cwd: Path,
                capture: bool = False,
                timeout_seconds: float | None = None,
            ) -> str:
                calls.append(args)
                dispatched = any(
                    call[:3] == ["gh", "workflow", "run"] for call in calls
                )
                replies = {
                    ("gh", "pr", "view"): head,
                    ("gh", "run", "list", "tests.yml"): '[{"databaseId": 7}]',
                    ("gh", "api"): artifact_names,
                    # The publish run: a new id appears once it is dispatched.
                    ("gh", "run", "list"): (
                        f'[{{"databaseId": {9 if dispatched else 8}}}]'
                    ),
                }
                key = (*args[:3], *(["tests.yml"] if "tests.yml" in args else []))
                return replies.get(key, replies.get(tuple(args[:2]), ""))

            def try_run(self, args: list[str], *, cwd: Path) -> tuple[int, str]:
                if args[:3] == ["gh", "run", "list"]:
                    return 0, self.run(args, cwd=cwd)
                return 0, '[{"name": "test-bot"}]'

        class RecordingGit(FakeGit):
            def run(self, args: list[str], *, cwd: Path) -> None:
                calls.append(["git", *args])

        root = Path(__file__).resolve().parents[1]
        manifest = load_manifest(root, "sive")
        TapRelease(
            root,
            manifest,
            PullRequestProcess(b""),
            RecordingGit(),
            FakeGitHub("a" * 40),
        ).wait_and_publish(11, head)
        return calls

    def test_a_pull_request_without_a_bottle_is_never_published(self) -> None:
        with self.assertRaisesRegex(
            ReleaseError, r"#11: tests.yml run 7 uploaded no bottles_\* artifact"
        ):
            self._publish("")

    def test_nothing_is_dispatched_when_the_bottle_is_missing(self) -> None:
        calls: list[list[str]] = []
        try:
            calls = self._publish("")
        except ReleaseError:
            pass
        self.assertFalse(
            any(call[:3] == ["gh", "workflow", "run"] for call in calls),
            "publish.yml was dispatched without a bottle",
        )

    def test_a_pull_request_with_its_bottle_is_published(self) -> None:
        calls = self._publish("bottles_macos-26")

        self.assertTrue(any(call[:3] == ["gh", "workflow", "run"] for call in calls))


if __name__ == "__main__":
    unittest.main()
