"""Release notes: a Keep a Changelog section per product, from its own commits.

The real git-cliff runs against a throwaway repository, because `cliff.toml` is
the artifact under test: grouping, ordering and scoping live in that file.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from modules.engine.application.release_notes import (
    NotesSource,
    ReleaseNotes,
    render_release_notes,
    reviewed_section,
)
from modules.engine.infrastructure.adapters import GitAdapter, SubprocessAdapter
from modules.engine.infrastructure.manifest import load_manifest

TAP_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "PeachlifeAB/homebrew-tap"

# (path touched, commit subject), oldest first. Tags are placed between them.
# The sive release tag sits on a commit that touches packages/sive, as the real
# `release: prepare` commit does: git-cliff only reads tags on included paths.
HISTORY_BEFORE_SIVE_0_1_9 = (
    ("packages/sive/core.py", "feat(sive): first release"),
    ("packages/bgtail/core.py", "feat(bgtail): first release"),
    ("packages/sive/pyproject.toml", "release: prepare 0.1.9"),
)
HISTORY_AFTER_SIVE_0_1_9 = (
    ("packages/sive/setup.py", "feat(sive): non-interactive setup"),
    ("packages/sive/hook.sh", "fix(sive): make the hook pass style"),
    ("packages/bgtail/term.py", "feat(bgtail): linux terminal"),
    ("uv.lock", "chore(deps): bump virtualenv"),
    ("packages/sive/style.py", "style: satisfy tap syntax checks"),
    ("packages/sive/bottle.txt", "sive: add 0.1.10 bottle."),
    ("packages/sive/pyproject.toml", "release: prepare 0.1.10"),
    ("packages/sive/docs.md", "docs: describe the release"),
    ("packages/sive/creds.py", "refactor(sive): extract credentials"),
    ("packages/sive/old.py", "remove(sive): drop the legacy path"),
    ("packages/sive/warn.py", "deprecate(sive): warn about the old flag"),
    ("packages/sive/keys.py", "security(sive): refuse world-readable keys"),
)


def _commit(git: GitAdapter, repository: Path, path: str, subject: str) -> None:
    target = repository / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{subject}\n")
    git.run(["add", "-A"], cwd=repository)
    git.run(["commit", "-m", subject], cwd=repository)


def build_repository(root: Path, git: GitAdapter) -> Path:
    repository = root / "tap"
    repository.mkdir()
    git.run(["init", "-q", "-b", "main"], cwd=repository)
    for key, value in (
        ("user.name", "Test"),
        ("user.email", "test@example.com"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
    ):
        git.run(["config", key, value], cwd=repository)
    for path, subject in HISTORY_BEFORE_SIVE_0_1_9:
        _commit(git, repository, path, subject)
    git.run(["tag", "-a", "sive-0.1.9", "-m", "Release 0.1.9"], cwd=repository)
    git.run(["tag", "-a", "bgtail-0.1.2", "-m", "Release 0.1.2"], cwd=repository)
    for path, subject in HISTORY_AFTER_SIVE_0_1_9:
        _commit(git, repository, path, subject)
    return repository


class ReleaseNotesTests(unittest.TestCase):
    _tmp: tempfile.TemporaryDirectory[str]
    sive: ReleaseNotes
    bgtail: ReleaseNotes

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        process = SubprocessAdapter()
        source = NotesSource(
            repository=build_repository(Path(cls._tmp.name), GitAdapter(process)),
            config=TAP_ROOT / "cliff.toml",
            repository_slug=REPOSITORY,
        )
        cls.sive = render_release_notes(
            load_manifest(TAP_ROOT, "sive"), "0.1.10", source, process
        )
        cls.bgtail = render_release_notes(
            load_manifest(TAP_ROOT, "bgtail"), "0.1.3", source, process
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_the_section_is_titled_with_the_version_and_a_date(self) -> None:
        self.assertRegex(self.sive.section, r"^## \[0\.1\.10\] - \d{4}-\d{2}-\d{2}")

    def test_commit_types_land_in_the_groups_keep_a_changelog_names(self) -> None:
        groups = _entries_by_group(self.sive.section)

        self.assertEqual(groups["Added"], ["Non-interactive setup"])
        self.assertEqual(groups["Fixed"], ["Make the hook pass style"])
        self.assertEqual(groups["Changed"], ["Extract credentials"])
        self.assertEqual(groups["Removed"], ["Drop the legacy path"])
        self.assertEqual(groups["Deprecated"], ["Warn about the old flag"])
        self.assertEqual(groups["Security"], ["Refuse world-readable keys"])

    def test_groups_follow_the_fixed_keep_a_changelog_order(self) -> None:
        order = [
            m.group(1)
            for m in re.finditer(r"^### (\w+)", self.sive.section, re.MULTILINE)
        ]

        self.assertEqual(
            order,
            ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"],
        )

    def test_maintenance_and_release_commits_are_not_announced(self) -> None:
        for leaked in ("virtualenv", "syntax", "bottle", "prepare", "describe"):
            with self.subTest(leaked=leaked):
                self.assertNotIn(leaked, self.sive.section.lower())

    def test_only_the_products_own_commits_are_listed(self) -> None:
        self.assertNotIn("terminal", self.sive.section.lower())
        self.assertEqual(
            _entries_by_group(self.bgtail.section), {"Added": ["Linux terminal"]}
        )

    def test_the_changelog_links_the_comparison_with_the_previous_release(self) -> None:
        self.assertIn(
            f"[0.1.10]: https://github.com/{REPOSITORY}/compare/sive-0.1.9...sive-0.1.10",
            self.sive.changelog,
        )

    def test_the_changelog_carries_the_keep_a_changelog_header(self) -> None:
        self.assertIn("# Changelog", self.sive.changelog)
        self.assertIn("keepachangelog.com", self.sive.changelog)

    def test_the_section_is_part_of_the_changelog(self) -> None:
        self.assertIn(self.sive.section, self.sive.changelog)

    def test_the_changelog_keeps_every_earlier_release_of_the_product(self) -> None:
        """CHANGELOG.md is the whole history, so an earlier release stays in it."""
        self.assertIn("## [0.1.9]", self.sive.changelog)
        self.assertNotIn("## [0.1.9]", self.sive.section)


CHANGELOG = """# Changelog

## [0.1.10] - 2026-10-10

### Fixed

- Stop the hook re-entering itself

## [0.1.9] - 2026-09-20

No notes were written.

[0.1.10]: https://example.invalid/compare/sive-0.1.9...sive-0.1.10
[0.1.9]: https://example.invalid/compare/sive-0.1.8...sive-0.1.9
"""


class ReviewedSectionTests(unittest.TestCase):
    def test_a_section_ends_where_the_next_release_begins(self) -> None:
        self.assertEqual(
            reviewed_section(CHANGELOG, "0.1.10"),
            (
                "## [0.1.10] - 2026-10-10\n\n### Fixed\n\n"
                "- Stop the hook re-entering itself"
            ),
        )

    def test_the_oldest_section_ends_at_the_comparison_links(self) -> None:
        self.assertEqual(
            reviewed_section(CHANGELOG, "0.1.9"),
            "## [0.1.9] - 2026-09-20\n\nNo notes were written.",
        )

    def test_a_version_without_a_section_has_none(self) -> None:
        self.assertIsNone(reviewed_section(CHANGELOG, "0.1.8"))

    def test_a_version_is_matched_whole_not_as_a_prefix(self) -> None:
        self.assertIsNone(reviewed_section(CHANGELOG, "0.1.1"))


def _entries_by_group(section: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    current = ""
    for line in section.splitlines():
        if heading := re.match(r"### (\w+)", line):
            current = heading.group(1)
            groups[current] = []
        elif line.startswith("- ") and current:
            groups[current].append(line[2:].strip())
    return groups


if __name__ == "__main__":
    unittest.main()
