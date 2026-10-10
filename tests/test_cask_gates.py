"""A cask bump runs the gates that apply to a cask, and says which it skips.

The cask is generated and released upstream, so the tap checks the proposed bump
(the generated file sitting in the working tree) before it is committed, and the
bump is announced by one line in the tap's CHANGELOG.md. The git state is real:
a throwaway repository with a bare remote.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.engine.application.cask_release import (
    ANNOUNCEMENT_FILE,
    CASK_SHARED_GATES,
    CASK_SKIPPED_GATES,
    CaskRelease,
)
from modules.engine.domain.models import CaskManifest, ReleaseError
from modules.engine.infrastructure.adapters import GitAdapter, SubprocessAdapter
from modules.engine.infrastructure.manifest import load_product
from tests.test_producer import FakeProcess

TAP_ROOT = Path(__file__).resolve().parents[1]
CASK_PATH = "Casks/hyprspace.rb"
OFFENSE = "Cask/StanzaOrder: stanzas out of order"


def _cask(version: str, extra: str = "") -> str:
    return (
        'cask "hyprspace" do\n'
        f'  version "{version}"\n'
        '  sha256 "0000"\n'
        '  url "https://example.invalid/Hyprspace-v#{version}.zip"\n'
        f"{extra}"
        "  depends_on macos: :sequoia\n"
        "end\n"
    )


def _changelog(*lines: str) -> str:
    entries = "".join(f"{line}\n" for line in lines)
    return f"# Changelog\n\n## Casks\n\n{entries}"


class StyleProcess(FakeProcess):
    """brew style is scripted; everything real runs through git."""

    def __init__(self, *, offense: str | None = None) -> None:
        super().__init__()
        self.offense = offense

    def try_run(self, args: list[str], *, cwd: Path) -> tuple[int, str]:
        self.commands.append(args)
        if args[:2] == ["brew", "style"]:
            return (1, self.offense) if self.offense else (0, "")
        return 0, ""


class CaskTapCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "tap"
        origin = Path(tmp.name) / "origin.git"
        self.origin = origin
        # Another repository the tap owns, such as the cask's source.
        self.source = Path(tmp.name) / "source.git"
        self.git = GitAdapter(SubprocessAdapter())
        self.root.mkdir()
        origin.mkdir()
        self.git.run(["init", "-q", "--bare", "-b", "main"], cwd=origin)
        self.git.run(["init", "-q", "-b", "main"], cwd=self.root)
        for key, value in (("user.name", "Test"), ("user.email", "t@example.com")):
            self.git.run(["config", key, value], cwd=self.root)
        manifest = load_product(TAP_ROOT, "hyprspace")
        assert isinstance(manifest, CaskManifest)
        self.manifest = manifest
        self._write(CASK_PATH, _cask("0.4.0"))
        self._write(ANNOUNCEMENT_FILE, _changelog(self._announcement("0.4.0")))
        self._write("README.md", "tap\n")
        self.git.run(["add", "-A"], cwd=self.root)
        self.git.run(["commit", "-q", "-m", "hyprspace: v0.4.0"], cwd=self.root)
        self.git.run(["remote", "add", "origin", str(origin)], cwd=self.root)
        self.git.run(["push", "-q", "-u", "origin", "main"], cwd=self.root)
        self.source.mkdir()
        self.git.run(["init", "-q", "--bare", "-b", "main"], cwd=self.source)
        self.git.run(["push", "-q", str(self.source), "main"], cwd=self.root)

    def _announcement(self, version: str) -> str:
        return f"- hyprspace {version}: {self.manifest.release_notes_url(version)}"

    def _write(self, path: str, text: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def _bump(self, version: str, extra: str = "", announce: bool = True) -> None:
        """The generated cask, and the changelog line that announces it."""
        self._write(CASK_PATH, _cask(version, extra))
        if announce:
            self._write(
                ANNOUNCEMENT_FILE,
                _changelog(self._announcement(version), self._announcement("0.4.0")),
            )

    def _release(self, process: FakeProcess | None = None) -> CaskRelease:
        return CaskRelease(
            self.manifest,
            self.root,
            process or StyleProcess(),
            self.git,
            (str(self.origin), str(self.source)),
        )

    def _check(self, version: str, process: FakeProcess | None = None) -> list[str]:
        lines: list[str] = []
        self._release(process).check(version, report=lines.append)
        return lines

    def _head(self) -> str:
        return self.git.output(["rev-parse", "HEAD"], cwd=self.root)


class CaskGateTests(CaskTapCase):
    def test_a_dependabot_branch_on_the_remote_stops_the_release_first(
        self,
    ) -> None:
        self._bump("0.5.0")
        self.git.run(
            ["push", "-q", "origin", "HEAD:refs/heads/dependabot/uv/dev-1"],
            cwd=self.root,
        )
        lines: list[str] = []

        with self.assertRaisesRegex(
            ReleaseError,
            "no-dependabot-branches: Dependabot PR detected and must be handled "
            f"before release: {self.origin} dependabot/uv/dev-1",
        ):
            self._release().check("0.5.0", report=lines.append)
        self.assertEqual(
            [line for line in lines if line.startswith("ok")],
            [],
            "a gate ran before the Dependabot check",
        )

    def test_a_dependabot_branch_on_another_owned_repository_stops_it_too(
        self,
    ) -> None:
        """Every product's repositories are checked, whichever is released."""
        self._bump("0.5.0")
        self.git.run(
            ["push", "-q", str(self.source), "HEAD:refs/heads/dependabot/npm/web-1"],
            cwd=self.root,
        )

        with self.assertRaisesRegex(
            ReleaseError, f"{self.source} dependabot/npm/web-1"
        ):
            self._check("0.5.0")

    def test_no_dependabot_branch_anywhere_passes_the_check(self) -> None:
        self._bump("0.5.0")

        self.assertIn("ok   no-dependabot-branches (instant)", self._check("0.5.0"))

    def test_the_check_sees_commits_pushed_since_the_last_fetch(self) -> None:
        """A remote commit made elsewhere must stop the release even when no
        fetch ran locally: the check fetches before it compares."""
        self._bump("0.5.0")
        other = self.root.parent / "other"
        self.git.run(
            ["clone", "-q", str(self.root.parent / "origin.git"), str(other)],
            cwd=self.root.parent,
        )
        for key, value in (("user.name", "Test"), ("user.email", "t@example.com")):
            self.git.run(["config", key, value], cwd=other)
        self.git.run(["commit", "-q", "--allow-empty", "-m", "elsewhere"], cwd=other)
        self.git.run(["push", "-q", "origin", "main"], cwd=other)

        with self.assertRaisesRegex(ReleaseError, "synced-with-remote: .*1 behind"):
            self._check("0.5.0")

    def test_a_bump_that_changes_only_the_cask_and_its_announcement_passes(
        self,
    ) -> None:
        self._bump("0.5.0")

        lines = self._check("0.5.0")

        self.assertTrue(any(line.startswith("ok   cask-version") for line in lines))
        self.assertTrue(any(line.startswith("ok   cask-announced") for line in lines))

    def test_the_checks_list_each_formula_gate_a_cask_skips_with_the_reason(
        self,
    ) -> None:
        self._bump("0.5.0")

        lines = self._check("0.5.0")

        for gate, reason in CASK_SKIPPED_GATES.items():
            with self.subTest(gate=gate):
                self.assertIn(f"skip {gate} (cask: {reason})", lines)

    def test_another_changed_path_stops_the_bump_and_names_it(self) -> None:
        self._bump("0.5.0")
        self._write("README.md", "changed\n")

        with self.assertRaisesRegex(ReleaseError, r"only-the-cask-changed.*README\.md"):
            self._check("0.5.0")

    def test_the_cask_version_must_be_the_requested_one(self) -> None:
        self._bump("0.5.0")

        with self.assertRaisesRegex(ReleaseError, "cask-version.*0.5.0.*0.6.0"):
            self._check("0.6.0")

    def test_the_version_must_exceed_the_committed_one(self) -> None:
        self._bump("0.4.0", "  # touched\n", announce=False)

        with self.assertRaisesRegex(ReleaseError, "cask-version.*must exceed 0.4.0"):
            self._check("0.4.0")

    def test_a_bump_without_its_announcement_stops_and_names_the_command(self) -> None:
        self._bump("0.5.0", announce=False)

        with self.assertRaisesRegex(
            ReleaseError, r"cask-announced.*hyprspace 0\.5\.0.*notes 0\.5\.0"
        ):
            self._check("0.5.0")

    def test_an_announcement_linking_another_version_stops_the_bump(self) -> None:
        self._write(CASK_PATH, _cask("0.5.0"))
        self._write(
            ANNOUNCEMENT_FILE,
            _changelog(self._announcement("0.5.1"), self._announcement("0.4.0")),
        )

        with self.assertRaisesRegex(ReleaseError, "cask-announced"):
            self._check("0.5.0")

    def test_a_style_offense_stops_before_anything_is_committed(self) -> None:
        self._bump("0.5.0")
        before = self._head()

        with self.assertRaisesRegex(ReleaseError, r"(?s)brew-style-cask.*StanzaOrder"):
            self._check("0.5.0", StyleProcess(offense=OFFENSE))

        self.assertEqual(self._head(), before)

    def test_a_cask_declaring_intel_support_stops_the_bump(self) -> None:
        for declaration in (
            "  depends_on arch: :intel\n",
            "  depends_on arch: [:arm64, :x86_64]\n",
        ):
            with self.subTest(declaration=declaration.strip()):
                self._bump("0.5.0", declaration)

                with self.assertRaisesRegex(ReleaseError, "no-intel-declared"):
                    self._check("0.5.0")

    def test_the_repository_state_gates_apply_to_a_cask_too(self) -> None:
        self._bump("0.5.0")
        self.git.run(["switch", "-q", "-c", "topic"], cwd=self.root)

        with self.assertRaisesRegex(ReleaseError, "release-branch"):
            self._check("0.5.0")

    def test_the_cheap_checks_run_before_brew_style(self) -> None:
        self._bump("0.5.0", announce=False)
        process = StyleProcess()

        with self.assertRaises(ReleaseError):
            self._check("0.5.0", process)

        self.assertNotIn(["brew", "style"], [c[:2] for c in process.commands])


class CaskAnnouncementTests(CaskTapCase):
    """The announcement is one line, newest first, under the Casks heading."""

    def test_announce_puts_the_line_under_casks_above_older_ones(self) -> None:
        self._release().announce("0.5.0")

        text = (self.root / ANNOUNCEMENT_FILE).read_text(encoding="utf-8")
        self.assertIn(f"## Casks\n\n{self._announcement('0.5.0')}\n", text)
        self.assertLess(
            text.index(self._announcement("0.5.0")),
            text.index(self._announcement("0.4.0")),
        )

    def test_announce_twice_writes_one_line(self) -> None:
        self._release().announce("0.5.0")
        self._release().announce("0.5.0")

        text = (self.root / ANNOUNCEMENT_FILE).read_text(encoding="utf-8")
        self.assertEqual(text.count(self._announcement("0.5.0")), 1)

    def test_announce_keeps_the_rest_of_the_changelog(self) -> None:
        self._write(ANNOUNCEMENT_FILE, "# Changelog\n\nkept\n\n## Casks\n\n")

        self._release().announce("0.5.0")

        text = (self.root / ANNOUNCEMENT_FILE).read_text(encoding="utf-8")
        self.assertIn("kept", text)
        self.assertIn(self._announcement("0.5.0"), text)

    def test_announce_refuses_an_invalid_version_before_writing(self) -> None:
        before = (self.root / ANNOUNCEMENT_FILE).read_text(encoding="utf-8")

        with self.assertRaises(ReleaseError):
            self._release().announce("not-a-version")

        after = (self.root / ANNOUNCEMENT_FILE).read_text(encoding="utf-8")
        self.assertEqual(after, before)


class CaskCommandTests(unittest.TestCase):
    """The command line a person types, driven through the real entry point."""

    def _run(self, *argv: str) -> tuple[int, str, str]:
        from modules.engine.api.cli import main

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--product", "hyprspace", "--project-root", ".", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_a_real_release_of_a_cask_is_refused_with_the_reason(self) -> None:
        code, _, err = self._run("release", "0.5.0")

        self.assertEqual(code, 1)
        self.assertIn("hyprspace is a cask, released by", err)
        self.assertIn("release 0.5.0 --check", err)

    def test_every_formula_only_command_is_refused_for_a_cask(self) -> None:
        for command in ("observe", "verify", "prepare", "publish", "post-verify"):
            with self.subTest(command=command):
                code, _, err = self._run(command, "0.5.0")

                self.assertEqual(code, 1)
                self.assertIn(f"`{command}` is for formulae", err)

    def test_check_lists_the_skipped_gates_before_running_the_rest(self) -> None:
        _, out, _ = self._run("release", "0.5.0", "--check")

        for gate in CASK_SKIPPED_GATES:
            with self.subTest(gate=gate):
                self.assertIn(f"skip {gate} (cask:", out)

    def test_notes_announces_the_cask_and_prints_its_line(self) -> None:
        class RecordingCask:
            def __init__(self) -> None:
                self.versions: list[str] = []

            def announce(self, version: str) -> str:
                self.versions.append(version)
                return "- hyprspace 0.5.0: https://example.invalid/v0.5.0"

        recording = RecordingCask()
        with patch("modules.engine.api.cli.build_cask", return_value=recording):
            code, out, _ = self._run("notes", "0.5.0")

        self.assertEqual(code, 0)
        self.assertEqual(recording.versions, ["0.5.0"])
        self.assertIn("- hyprspace 0.5.0: https://example.invalid/v0.5.0", out)


class CaskGatePartitionTests(unittest.TestCase):
    def test_every_formula_gate_is_shared_with_a_cask_or_skipped_for_it(self) -> None:
        """Adding a formula gate forces a decision about casks: either the cask
        ladder reuses it or this table says why it does not apply."""
        from tests.test_gates import formula_gate_names

        self.assertEqual(
            formula_gate_names(),
            set(CASK_SHARED_GATES) | set(CASK_SKIPPED_GATES),
        )

    def test_no_gate_is_both_shared_and_skipped(self) -> None:
        self.assertEqual(CASK_SHARED_GATES & set(CASK_SKIPPED_GATES), set())


if __name__ == "__main__":
    unittest.main()
