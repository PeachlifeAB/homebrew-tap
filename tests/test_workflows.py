from __future__ import annotations

import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


class WorkflowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.tests = (root / ".github/workflows/tests.yml").read_text()
        self.publish = (root / ".github/workflows/publish.yml").read_text()

    def test_required_macos_matrix_and_bottle_artifacts(self) -> None:
        # Intel macOS is Homebrew support tier 3 and gets no new bottles.
        self.assertIn("os: [macos-26]", self.tests)
        self.assertNotIn("intel", self.tests)
        self.assertIn("brew test-bot --only-formulae", self.tests)
        self.assertIn("bottles_${{ matrix.os }}", self.tests)

    def test_a_formula_test_bot_skipped_or_failed_fails_the_pull_request(
        self,
    ) -> None:
        """test-bot ignores a failed `brew test` for a formula without a bottle
        for its current version, which is every release pull request here, and
        still exits 0; the check after it turns that into a red PR."""
        formulae = self.tests.index("brew test-bot --only-formulae")
        check = self.tests.index("bin/require-formulae-passed")
        self.assertGreater(check, formulae, "the check must run after test-bot")
        step = self.tests[self.tests.rindex("- ", 0, check) : check]
        self.assertIn("github.event_name == 'pull_request'", step)

    def test_actions_are_commit_pinned(self) -> None:
        uses = re.findall(r"uses: ([^\s]+)", self.tests + self.publish)
        self.assertTrue(uses)
        for action in uses:
            self.assertRegex(action, r"@[0-9a-f]{40}$")

    def test_publish_requires_pinned_head(self) -> None:
        self.assertIn("head_sha:", self.publish)
        self.assertIn("required: true", self.publish)
        self.assertIn('--head-sha="$HEAD_SHA"', self.publish)
        self.assertNotIn("packages: write", self.publish)


class ShellcheckCoverageTests(unittest.TestCase):
    def test_every_bash_script_in_bin_is_shellchecked(self) -> None:
        """qlty matches shell by extension and missed the extensionless bash
        scripts in bin/, so each must be named in its shell file type."""
        root = Path(__file__).resolve().parents[1]
        config = tomllib.loads((root / ".qlty/qlty.toml").read_text())
        globs = set(config["file_types"]["shell"]["globs"])
        for script in sorted((root / "bin").iterdir()):
            if not script.is_file():
                continue
            first_line = script.read_text().splitlines()[0]
            if re.search(r"\b(ba)?sh$", first_line):
                with self.subTest(script=script.name):
                    self.assertIn(f"bin/{script.name}", globs)


class RequireFormulaePassedTests(unittest.TestCase):
    """`bin/require-formulae-passed` reads the report `brew test-bot` writes:
    `skipped_or_failed_formulae-<bottle tag>.txt`, empty when all passed."""

    SCRIPT = Path(__file__).resolve().parents[1] / "bin/require-formulae-passed"
    REPORT = "skipped_or_failed_formulae-arm64_tahoe.txt"

    def _run(self, report: str | None) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            if report is not None:
                (Path(tmp) / self.REPORT).write_text(report)
            return subprocess.run(
                [str(self.SCRIPT)],
                cwd=tmp,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_an_empty_report_passes(self) -> None:
        self.assertEqual(self._run("").returncode, 0)

    def test_a_skipped_or_failed_formula_fails_and_is_named(self) -> None:
        result = self._run("peachlifeab/tap/sive")

        self.assertEqual(result.returncode, 1)
        self.assertIn("peachlifeab/tap/sive", result.stderr)

    def test_a_missing_report_fails_closed(self) -> None:
        result = self._run(None)

        self.assertEqual(result.returncode, 1)
        self.assertIn("skipped_or_failed_formulae", result.stderr)


if __name__ == "__main__":
    unittest.main()
