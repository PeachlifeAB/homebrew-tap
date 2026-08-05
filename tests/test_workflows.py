from __future__ import annotations

import re
import unittest
from pathlib import Path


class WorkflowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.tests = (root / ".github/workflows/tests.yml").read_text()
        self.publish = (root / ".github/workflows/publish.yml").read_text()

    def test_required_macos_matrix_and_bottle_artifacts(self) -> None:
        self.assertIn("macos-26", self.tests)
        self.assertIn("macos-26-intel", self.tests)
        self.assertIn("brew test-bot --only-formulae", self.tests)
        self.assertIn("bottles_${{ matrix.os }}", self.tests)

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


if __name__ == "__main__":
    unittest.main()
