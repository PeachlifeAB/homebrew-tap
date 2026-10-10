"""The release notes are a reviewed artifact.

`notes` writes CHANGELOG.md and prints it in full; a person reviews it; `release`
only verifies that the reviewed file exists, names the version, and differs from
the file at the last release. `release` never writes the notes itself, so what
gets published is what was reviewed.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from modules.engine.application.gates import GateCost, run_gates
from modules.engine.application.ports import ReleasePorts
from modules.engine.application.producer import ProducerRelease
from modules.engine.domain.models import ReleaseError
from modules.engine.infrastructure.adapters import GitAdapter, SubprocessAdapter
from modules.engine.infrastructure.manifest import load_manifest
from tests.test_producer import FakeGitHub, FakeHasher

TAP_ROOT = Path(__file__).resolve().parents[1]

RELEASED = "## [0.1.9] - 2026-09-20\n\n### Added\n\n- First release\n"
PENDING = (
    "## [0.1.10] - 2026-10-10\n\n### Fixed\n\n"
    "- Stop the mise hook re-entering itself\n\n" + RELEASED
)
GIT_CONFIG = (
    ("user.name", "Test"),
    ("user.email", "test@example.com"),
    ("commit.gpgsign", "false"),
    ("tag.gpgsign", "false"),
)


def _release_repository(root: Path, git: GitAdapter) -> Path:
    """A tap with sive 0.1.9 released: its CHANGELOG.md is committed and tagged."""
    repository = root / "tap"
    package = repository / "packages" / "sive"
    package.mkdir(parents=True)
    git.run(["init", "-q", "-b", "main"], cwd=repository)
    for key, value in GIT_CONFIG:
        git.run(["config", key, value], cwd=repository)
    (package / "CHANGELOG.md").write_text(RELEASED)
    git.run(["add", "-A"], cwd=repository)
    git.run(["commit", "-m", "release: sive 0.1.9"], cwd=repository)
    git.run(["tag", "-a", "sive-0.1.9", "-m", "Release 0.1.9"], cwd=repository)
    return repository


class NotesGateTests(unittest.TestCase):
    def _refusal(self, current: str | None) -> str:
        """The notes gate's refusal against `current` (None: no file), or "" to pass."""
        process = SubprocessAdapter()
        git = GitAdapter(process)
        with tempfile.TemporaryDirectory() as tmp:
            repository = _release_repository(Path(tmp), git)
            package = repository / "packages" / "sive"
            changelog = package / "CHANGELOG.md"
            if current is None:
                changelog.unlink()
            else:
                changelog.write_text(current)
            producer = ProducerRelease(
                load_manifest(TAP_ROOT, "sive"),
                package,
                ReleasePorts(process, git, FakeGitHub(), FakeHasher()),
            )
            try:
                run_gates(producer.notes_gate("0.1.10"), report=lambda _: None)
            except ReleaseError as error:
                return str(error)
        return ""

    def test_a_file_unchanged_since_the_last_release_stops_the_release(self) -> None:
        refusal = self._refusal(RELEASED)

        self.assertIn("unchanged since sive-0.1.9", refusal)
        self.assertIn("0.1.10", refusal)

    def test_a_file_without_a_section_for_the_version_stops_the_release(self) -> None:
        refusal = self._refusal("## [0.1.9] - 2026-09-20\n\n- edited by hand\n")

        self.assertIn("no section for 0.1.10", refusal)

    def test_a_missing_file_stops_the_release(self) -> None:
        refusal = self._refusal(None)

        self.assertIn("no CHANGELOG.md", refusal)

    def test_a_reviewed_section_for_the_version_passes(self) -> None:
        self.assertEqual(self._refusal(PENDING), "")

    def test_the_notes_gate_is_instant(self) -> None:
        """It reads one file and git history; it never builds or calls the network."""
        process = SubprocessAdapter()
        producer = ProducerRelease(
            load_manifest(TAP_ROOT, "sive"),
            TAP_ROOT / "packages" / "sive",
            ReleasePorts(process, GitAdapter(process), FakeGitHub(), FakeHasher()),
        )

        (gate,) = producer.notes_gate("0.1.10")

        self.assertEqual(gate.cost, GateCost.INSTANT)


if __name__ == "__main__":
    unittest.main()
