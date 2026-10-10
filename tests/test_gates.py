"""Release gates: cheapest check first, stop at the first failure, change nothing.

The same gates govern every product in `release-products/*.toml`; nothing in
here names a product except the parametrised tests that prove that.
"""

from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.engine.application.gates import Gate, GateCost, run_gates
from modules.engine.application.ports import ReleasePorts
from modules.engine.application.producer import ProducerRelease
from modules.engine.application.tap import TapRelease
from modules.engine.domain.models import (
    ReleaseError,
    ReleaseObservation,
    RepositoryState,
)
from modules.engine.infrastructure.manifest import load_manifest
from tests.test_producer import FakeGit, FakeGitHub, FakeHasher, FakeProcess

TAP_ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = ("sive", "bgtail", "lgtvctrl")


def _state(
    *,
    branch: str = "main",
    tracking: str = "origin/main",
    ahead: int = 0,
    behind: int = 0,
    dirty: tuple[str, ...] = (),
    dependabot_branches: tuple[str, ...] = (),
) -> RepositoryState:
    return RepositoryState(
        branch, "a" * 40, tracking, ahead, behind, dirty, dependabot_branches
    )


def _observation(
    product: str,
    *,
    repository: RepositoryState | None = None,
    declared_version: str = "0.1.9",
    remote_tag_commit: str | None = None,
    github_release_exists: bool = False,
) -> ReleaseObservation:
    return ReleaseObservation(
        load_manifest(TAP_ROOT, product),
        repository or _state(),
        declared_version,
        declared_version,
        None,
        remote_tag_commit,
        github_release_exists,
    )


class RunGatesTests(unittest.TestCase):
    def test_cheapest_runs_first_and_ties_keep_declaration_order(self) -> None:
        ran: list[str] = []

        def gate(name: str, cost: GateCost) -> Gate:
            return Gate(name, cost, lambda: ran.append(name))

        run_gates(
            [
                gate("tests", GateCost.MINUTES),
                gate("git-clean", GateCost.INSTANT),
                gate("style", GateCost.SECONDS),
                gate("tag-free", GateCost.INSTANT),
            ],
            report=lambda _: None,
        )

        self.assertEqual(ran, ["git-clean", "tag-free", "style", "tests"])

    def test_first_failure_stops_the_ladder_and_names_the_gate(self) -> None:
        ran: list[str] = []
        lines: list[str] = []

        def failing() -> None:
            raise ReleaseError("offenses detected")

        gates = [
            Gate("git-clean", GateCost.INSTANT, lambda: ran.append("git-clean")),
            Gate("style", GateCost.SECONDS, failing),
            Gate("tests", GateCost.MINUTES, lambda: ran.append("tests")),
        ]
        with self.assertRaisesRegex(ReleaseError, "^style: offenses detected$"):
            run_gates(gates, report=lines.append)

        self.assertEqual(ran, ["git-clean"])
        self.assertEqual(lines, ["ok   git-clean (instant)"])


class StartGateTests(unittest.TestCase):
    """The cheap repository-state gates, one failure class each."""

    def _failure(self, observation: ReleaseObservation) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nname = "sive"\n')
            process, git = FakeProcess(), FakeGit()
            release = ProducerRelease(
                load_manifest(TAP_ROOT, "sive"),
                root,
                ReleasePorts(process, git, FakeGitHub(), FakeHasher()),
            )
            gates = release.start_gates(observation, "0.1.10")
            with self.assertRaises(ReleaseError) as caught:
                run_gates(gates, report=lambda _: None)
            self.assertEqual(process.commands, [], "a failed gate ran a command")
            self.assertEqual(git.commands, [], "a failed gate touched git")
            return str(caught.exception)

    def test_each_failure_class_stops_at_its_own_gate(self) -> None:
        cases = {
            "release branch must be main": _observation(
                "sive", repository=_state(branch="feature")
            ),
            "Dependabot PR detected and must be handled before release": (
                _observation(
                    "sive",
                    repository=_state(dependabot_branches=("dependabot/uv/dev-1",)),
                )
            ),
            "producer worktree is dirty": _observation(
                "sive", repository=_state(dirty=(" M AGENTS.md",))
            ),
            "no tracking branch": _observation("sive", repository=_state(tracking="")),
            "producer differs from origin/main: 1 ahead": _observation(
                "sive", repository=_state(ahead=1)
            ),
            "must exceed 0.1.10": _observation("sive", declared_version="0.1.10"),
            "release tag already exists": _observation(
                "sive", remote_tag_commit="b" * 40
            ),
            "GitHub release already exists": _observation(
                "sive", github_release_exists=True
            ),
        }
        for expected, observation in cases.items():
            with self.subTest(expected=expected):
                self.assertIn(expected, self._failure(observation))

    def test_a_resume_is_held_to_the_same_repository_state(self) -> None:
        """`resume` continues a release whose tag exists, so it skips the tag
        and version gates, but never the Dependabot or upstream ones."""
        with tempfile.TemporaryDirectory() as tmp:
            release = ProducerRelease(
                load_manifest(TAP_ROOT, "sive"),
                Path(tmp),
                ReleasePorts(FakeProcess(), FakeGit(), FakeGitHub(), FakeHasher()),
            )
            blocked = _observation(
                "sive",
                repository=_state(dependabot_branches=("origin dependabot/uv/x",)),
                remote_tag_commit="b" * 40,
                github_release_exists=True,
            )

            with self.assertRaisesRegex(ReleaseError, "Dependabot PR detected"):
                release.require_resumable(blocked)
            release.require_resumable(_observation("sive", remote_tag_commit="b" * 40))

    def test_project_root_must_be_the_package_directory(self) -> None:
        """`prepare` writes <project-root>/pyproject.toml while reads look in
        packages/<name>/ first, so the tap root passes a dry run and then edits
        the wrong file in a real one."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nname = "homebrew-tap"\n')
            release = ProducerRelease(
                load_manifest(TAP_ROOT, "sive"),
                root,
                ReleasePorts(FakeProcess(), FakeGit(), FakeGitHub(), FakeHasher()),
            )
            gates = release.start_gates(_observation("sive"), "0.1.10")

            with self.assertRaisesRegex(ReleaseError, "--project-root packages/sive"):
                run_gates(gates, report=lambda _: None)

    def test_a_clean_package_root_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nname = "sive"\n')
            release = ProducerRelease(
                load_manifest(TAP_ROOT, "sive"),
                root,
                ReleasePorts(FakeProcess(), FakeGit(), FakeGitHub(), FakeHasher()),
            )

            run_gates(
                release.start_gates(_observation("sive"), "0.1.10"),
                report=lambda _: None,
            )

    def test_the_reviewed_notes_are_the_one_change_a_release_starts_with(
        self,
    ) -> None:
        """`notes` writes the file for review and the prepare commit carries it
        with the version bump, so it is uncommitted when the release starts."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nname = "sive"\n')
            release = ProducerRelease(
                load_manifest(TAP_ROOT, "sive"),
                root,
                ReleasePorts(FakeProcess(), FakeGit(), FakeGitHub(), FakeHasher()),
            )
            notes_only = _observation(
                "sive", repository=_state(dirty=("M packages/sive/CHANGELOG.md",))
            )

            run_gates(release.start_gates(notes_only, "0.1.10"), report=lambda _: None)

    def test_any_other_change_beside_the_notes_stops_the_release(self) -> None:
        dirty = (" M packages/sive/CHANGELOG.md", " M README.md")
        message = self._failure(_observation("sive", repository=_state(dirty=dirty)))

        self.assertIn("clean-worktree", message)
        self.assertIn("README.md", message)
        self.assertNotIn("CHANGELOG.md", message)


class TapGateTests(unittest.TestCase):
    def _tap(self, product: str, process: FakeProcess) -> TapRelease:
        return TapRelease(
            TAP_ROOT,
            load_manifest(TAP_ROOT, product),
            process,
            FakeGit(),
            FakeGitHub(),
        )

    def test_brew_style_offenses_stop_the_release(self) -> None:
        class StyleOffenses(FakeProcess):
            def try_run(self, args: list[str], *, cwd: Path) -> tuple[int, str]:
                self.commands.append(args)
                if args[:2] == ["brew", "style"]:
                    return 1, "env.sh line 14: SC2292"
                return 0, ""

        tap = self._tap("sive", StyleOffenses())

        with self.assertRaisesRegex(ReleaseError, "SC2292"):
            run_gates(tap.release_gates(), report=lambda _: None)

    def test_brew_style_covers_the_formula_and_every_tracked_shell_file(self) -> None:
        process = FakeProcess()
        tap = self._tap("sive", process)
        git_out = "bin/lib/a.sh\npackages/sive/src/sive/mise_hook/env.sh\n"
        with patch.object(tap.git, "output", return_value=git_out, create=True):
            run_gates(tap.release_gates(), report=lambda _: None)

        style = next(c for c in process.commands if c[:2] == ["brew", "style"])
        self.assertIn(str(TAP_ROOT / "Formula" / "sive.rb"), style)
        self.assertIn(str(TAP_ROOT / "bin/lib/a.sh"), style)
        self.assertIn(str(TAP_ROOT / "packages/sive/src/sive/mise_hook/env.sh"), style)

    def test_a_missing_publish_workflow_stops_the_release(self) -> None:
        class NoWorkflow(FakeProcess):
            def try_run(self, args: list[str], *, cwd: Path) -> tuple[int, str]:
                self.commands.append(args)
                if args[:3] == ["gh", "workflow", "view"]:
                    return 1, "could not find any workflows named publish.yml"
                return 0, ""

        tap = self._tap("sive", NoWorkflow())
        with (
            patch.object(tap.git, "output", return_value="", create=True),
            self.assertRaisesRegex(ReleaseError, "publish.yml"),
        ):
            run_gates(tap.release_gates(), report=lambda _: None)


def _sdist_bytes(version: str, *, extra: tarfile.TarInfo | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        body = f'[project]\nversion = "{version}"\n'.encode()
        info = tarfile.TarInfo(f"sive-{version}/pyproject.toml")
        info.size = len(body)
        archive.addfile(info, io.BytesIO(body))
        if extra is not None:
            archive.addfile(extra)
    return buffer.getvalue()


class SdistGateTests(unittest.TestCase):
    def _release(self, process: FakeProcess, root: Path) -> ProducerRelease:
        (root / "pyproject.toml").write_text('[project]\nname = "sive"\n')
        return ProducerRelease(
            load_manifest(TAP_ROOT, "sive"),
            root,
            ReleasePorts(process, FakeGit(), FakeGitHub(), FakeHasher()),
        )

    def _process_building(self, payload: bytes) -> FakeProcess:
        class BuildingProcess(FakeProcess):
            def run(self, args, *, cwd, capture=False, timeout_seconds=None):  # type: ignore[no-untyped-def]
                self.commands.append(args)
                if args[:3] == ["uv", "build", "--sdist"]:
                    out = Path(args[args.index("--out-dir") + 1])
                    (out / "sive-0.1.9.tar.gz").write_bytes(payload)
                return ""

        return BuildingProcess()

    def test_a_valid_sdist_passes_without_leaving_a_dist_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._release(self._process_building(_sdist_bytes("0.1.9")), root)

            run_gates(release.sdist_gates("0.1.9"), report=lambda _: None)

            self.assertFalse((root / "dist").exists())

    def test_an_sdist_with_a_symlink_stops_the_release(self) -> None:
        link = tarfile.TarInfo("sive-0.1.9/escape")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._release(
                self._process_building(_sdist_bytes("0.1.9", extra=link)), root
            )

            with self.assertRaisesRegex(ReleaseError, "unsafe members"):
                run_gates(release.sdist_gates("0.1.9"), report=lambda _: None)


def formula_gates(product: str) -> list[Gate]:
    """The real ladder a formula release runs, built the way `release` builds it,
    so a gate added anywhere in the engine shows up here without a second list."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest = load_manifest(TAP_ROOT, product)
        (root / "pyproject.toml").write_text(
            f'[project]\nname = "{manifest.package}"\n'
        )
        ports = ReleasePorts(FakeProcess(), FakeGit(), FakeGitHub(), FakeHasher())
        producer = ProducerRelease(manifest, root, ports)
        tap = TapRelease(TAP_ROOT, manifest, ports.process, ports.git, ports.github)
        with patch.object(producer, "observe", return_value=_observation(product)):
            return [*producer.release_gates("0.1.10"), *tap.release_gates()]


def formula_gate_names() -> set[str]:
    return {gate.name for gate in formula_gates("sive")}


class EveryProductShareOneLadderTests(unittest.TestCase):
    def test_the_same_gates_run_in_the_same_order_for_every_formula(self) -> None:
        ladders = {
            product: [
                (gate.name, gate.cost)
                for gate in sorted(formula_gates(product), key=lambda g: g.cost)
            ]
            for product in PRODUCTS
        }

        self.assertEqual(ladders["bgtail"], ladders["sive"])
        self.assertEqual(ladders["lgtvctrl"], ladders["sive"])
        costs = [cost for _, cost in ladders["sive"]]
        self.assertEqual(costs, sorted(costs), "ladder is not cheapest first")

    def test_an_open_dependabot_update_is_the_first_thing_a_release_checks(
        self,
    ) -> None:
        first = min(formula_gates("sive"), key=lambda g: g.cost)

        self.assertEqual(first.name, "no-dependabot-branches")


if __name__ == "__main__":
    unittest.main()
