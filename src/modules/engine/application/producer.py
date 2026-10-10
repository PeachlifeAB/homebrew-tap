from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..domain.models import (
    CommandFailed,
    Handoff,
    ProductManifest,
    ReleaseError,
    ReleaseObservation,
)
from .gates import Gate, GateCost, run_gates
from .observation import lock_path, locked_version, observe_repository, project_version
from .ports import ReleasePorts
from .release_notes import NOTES_FILE, reviewed_section
from .repository_gates import start_gates, state_gates
from .sdist import verify_sdist

# Workflows that must pass on the pushed prepare commit before the tag exists:
# tests.yml runs `brew test-bot --only-tap-syntax`, quality.yml runs qlty.
REQUIRED_CI_WORKFLOWS = ("tests.yml", "quality.yml")
CI_DISCOVERY_ATTEMPTS = 30
CI_WATCH_TIMEOUT_SECONDS = 1800.0

_PROJECT_VERSION = re.compile(r'^version = "[^"]+"$', re.MULTILINE)


@dataclass(frozen=True)
class PublicationStep:
    label: str
    run: Callable[[], None]


class ProducerRelease:
    def __init__(
        self,
        manifest: ProductManifest,
        project_root: Path,
        ports: ReleasePorts,
        watched_remotes: tuple[str, ...] = (),
    ) -> None:
        self.manifest = manifest
        self.project_root = project_root.resolve()
        self.ports = ports
        self.process = ports.process
        self.git = ports.git
        self.github = ports.github
        self.hasher = ports.hasher
        self.watched_remotes = watched_remotes
        """Every remote the tap owns; a Dependabot branch on any of them stops
        the release."""

    def observe(self, version: str) -> ReleaseObservation:
        return observe_repository(
            self.manifest, self.project_root, self.ports, version, self.watched_remotes
        )

    def start_gates(
        self, observation: ReleaseObservation, version: str
    ) -> tuple[Gate, ...]:
        """The repository-state gates: local, instant, run before anything else."""
        return start_gates(self.manifest, self.project_root, observation, version)

    def sdist_gates(self, expected_version: str) -> tuple[Gate, ...]:
        """Build the sdist where nothing can see it and verify what a release
        would publish. Checked before the tag exists, not after it is public."""

        def sdist_builds_and_verifies() -> None:
            with tempfile.TemporaryDirectory(prefix="sdist-check-") as out:
                self.process.run(
                    ["uv", "build", "--sdist", "--out-dir", out],
                    cwd=self.project_root,
                )
                asset = Path(out) / self.manifest.asset_name(expected_version)
                if not asset.is_file():
                    raise ReleaseError(f"expected sdist not produced: {asset.name}")
                verify_sdist(asset, expected_version)

        return (
            Gate(
                "sdist-builds-and-verifies", GateCost.SECONDS, sdist_builds_and_verifies
            ),
        )

    def quality_gates(self) -> tuple[Gate, ...]:
        def quality_task_passes() -> None:
            self.process.run(
                ["uv", "run", "poe", self.manifest.quality_task],
                cwd=self.project_root,
            )

        return (Gate("quality-task", GateCost.MINUTES, quality_task_passes),)

    def notes_gate(self, version: str) -> tuple[Gate, ...]:
        """The reviewed release notes exist, name this version, and differ from the
        file at the last release, so a release never publishes notes nobody
        reviewed for it. The gate reads one file and git history only."""

        def reviewed_notes_for_this_release() -> None:
            changelog = self.project_root / NOTES_FILE
            if not changelog.is_file():
                raise ReleaseError(
                    f"no {NOTES_FILE}: run the notes command for {version}, "
                    "review it, then release"
                )
            current = changelog.read_text(encoding="utf-8").strip()
            previous_tag = self._previous_release_tag()
            if previous_tag is not None and current == self._notes_at(previous_tag):
                raise ReleaseError(
                    f"{NOTES_FILE} is unchanged since {previous_tag}: run the notes "
                    f"command for {version}, review it, then release"
                )
            if f"## [{version}]" not in current:
                raise ReleaseError(
                    f"{NOTES_FILE} has no section for {version}: run the notes "
                    "command, review it, then release"
                )

        return (
            Gate("reviewed-notes", GateCost.INSTANT, reviewed_notes_for_this_release),
        )

    def _previous_release_tag(self) -> str | None:
        """The latest tag of this product, or None before its first release."""
        try:
            return self.git.output(
                [
                    "describe",
                    "--tags",
                    "--abbrev=0",
                    "--match",
                    f"{self.manifest.tag_prefix}*",
                ],
                cwd=self.project_root,
            )
        except CommandFailed:
            return None

    def _notes_at(self, tag: str) -> str | None:
        """The notes file as that tag recorded it, or None if it had none."""
        try:
            return self.git.output(
                ["show", f"{tag}:packages/{self.manifest.package}/{NOTES_FILE}"],
                cwd=self.project_root,
            ).strip()
        except CommandFailed:
            return None

    def release_gates(self, version: str) -> tuple[Gate, ...]:
        """Every check the producer owns, for `release --check` and `release`."""
        observation = self.observe(version)
        return (
            *self.start_gates(observation, version),
            *self.notes_gate(version),
            *self.sdist_gates(observation.declared_version),
            *self.quality_gates(),
        )

    def require_release_start(
        self, observation: ReleaseObservation, version: str
    ) -> None:
        run_gates(self.start_gates(observation, version), report=lambda _: None)

    def require_resumable(self, observation: ReleaseObservation) -> None:
        """A resume continues a release whose tag may exist, so the tag and
        version gates do not apply; the repository-state ones always do."""
        run_gates(state_gates(observation.repository))

    def prepare(self, version: str, *, dry_run: bool) -> None:
        observation = self.observe(version)
        self.require_release_start(observation, version)
        print(
            f"prepare {self.manifest.name} {observation.declared_version} -> {version}"
        )
        if dry_run:
            print(f"[dry-run] update pyproject.toml version to {version}")
            print("[dry-run] uv lock")
            print(f"[dry-run] uv run poe {self.manifest.quality_task}")
            return

        path = self.project_root / "pyproject.toml"
        content = path.read_text(encoding="utf-8")
        updated, count = _PROJECT_VERSION.subn(
            f'version = "{version}"', content, count=1
        )
        if count != 1:
            raise ReleaseError(f"expected one project version in {path}, got {count}")
        path.write_text(updated, encoding="utf-8")
        self.process.run(["uv", "lock"], cwd=self.project_root)
        self.process.run(
            ["uv", "run", "poe", self.manifest.quality_task], cwd=self.project_root
        )
        self.verify_prepared(version)

    def verify_prepared(self, version: str) -> None:
        self.manifest.validate_version(version)
        declared = project_version(self.project_root, self.manifest.package)
        locked = locked_version(self.project_root, self.manifest.package)
        if declared != version or locked != version:
            raise ReleaseError(
                f"prepared version mismatch: requested={version}, "
                f"pyproject={declared}, lock={locked}"
            )
        development_output = self.process.run(
            ["uv", "run", self.manifest.executable, "--version"],
            cwd=self.project_root,
            capture=True,
        )
        expected = f"{self.manifest.executable} {version}"
        if not development_output.startswith(expected):
            raise ReleaseError(
                f"development CLI version mismatch: expected prefix {expected!r}, "
                f"got {development_output!r}"
            )
        with tempfile.TemporaryDirectory(
            prefix=f"{self.manifest.name}-release-"
        ) as tmp:
            venv = Path(tmp) / "venv"
            self.process.run(["uv", "venv", str(venv)], cwd=self.project_root)
            self.process.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(venv / "bin" / "python"),
                    str(self.project_root),
                ],
                cwd=self.project_root,
            )
            installed_output = self.process.run(
                [str(venv / "bin" / self.manifest.executable), "--version"],
                cwd=venv,
                capture=True,
            )
        if installed_output != expected:
            raise ReleaseError(
                f"installed CLI version mismatch: expected {expected!r}, "
                f"got {installed_output!r}"
            )
        print(f"prepared version ok: {installed_output}")

    def publication_steps(self, version: str) -> tuple[PublicationStep, ...]:
        """Everything that makes a release public, in the one order it runs.

        Real runs and `--dry-run` both read this list, so neither can drift.
        Nothing checkable is left for after the tag: the sdist is verified
        before the commit, and the tag exists only once CI is green on the
        commit it names.
        """
        tag = self.manifest.tag(version)
        workflows = ", ".join(REQUIRED_CI_WORKFLOWS)
        return (
            PublicationStep(
                "verify the sdist builds and passes its checks",
                lambda: run_gates(self.sdist_gates(version), report=lambda _: None),
            ),
            PublicationStep(
                "git add pyproject.toml uv.lock CHANGELOG.md; "
                f"git commit -m 'release: prepare {version}'",
                lambda: self._commit_prepared(version),
            ),
            PublicationStep(
                "git push origin main",
                lambda: self.git.run(["push", "origin", "main"], cwd=self.project_root),
            ),
            PublicationStep(
                f"wait for {workflows} to pass on the pushed commit",
                self._wait_for_green_ci,
            ),
            PublicationStep(
                f"git tag -a {tag} -m 'Release {version}'",
                lambda: self._tag_release(version, tag),
            ),
            PublicationStep(
                f"git push origin {tag}",
                lambda: self.git.run(["push", "origin", tag], cwd=self.project_root),
            ),
        )

    def commit_tag_push(self, version: str, *, dry_run: bool) -> str:
        self.verify_prepared(version)
        for step in self.publication_steps(version):
            if dry_run:
                print(f"[dry-run] {step.label}")
            else:
                step.run()
        if dry_run:
            return "<dry-run>"
        return self.git.output(["rev-parse", "HEAD"], cwd=self.project_root)

    def _commit_prepared(self, version: str) -> None:
        # The lock may live at the workspace root, not beside the package.
        lock = os.path.relpath(lock_path(self.project_root), self.project_root)
        self.git.run(["add", "pyproject.toml", lock, NOTES_FILE], cwd=self.project_root)
        # Nothing staged means an earlier attempt already committed the bump,
        # so a retry after a CI failure continues instead of dying on commit.
        staged = self.git.output(
            ["diff", "--cached", "--name-only"], cwd=self.project_root
        )
        if staged.strip():
            self.git.run(
                ["commit", "-m", f"release: prepare {version}"], cwd=self.project_root
            )
        if project_version(self.project_root, self.manifest.package) != version:
            raise ReleaseError("release commit does not contain prepared version")

    def _wait_for_green_ci(self) -> None:
        """Wait for each required workflow on the pushed HEAD, event-driven by
        `gh run watch`, and fail before the tag exists if one does not pass."""
        commit = self.git.output(["rev-parse", "HEAD"], cwd=self.project_root)
        repository = self.manifest.repository
        for workflow in REQUIRED_CI_WORKFLOWS:
            listing = self.process.poll_until(
                [
                    "gh",
                    "run",
                    "list",
                    "--repo",
                    repository,
                    "--workflow",
                    workflow,
                    "--commit",
                    commit,
                    "--limit",
                    "1",
                    "--json",
                    "databaseId",
                ],
                cwd=self.project_root,
                ready=lambda code, out: code == 0 and bool(json.loads(out or "[]")),
                attempts=CI_DISCOVERY_ATTEMPTS,
            )
            self.process.run(
                [
                    "gh",
                    "run",
                    "watch",
                    str(json.loads(listing)[0]["databaseId"]),
                    "--repo",
                    repository,
                    "--exit-status",
                ],
                cwd=self.project_root,
                timeout_seconds=CI_WATCH_TIMEOUT_SECONDS,
            )

    def _tag_release(self, version: str, tag: str) -> None:
        commit = self.git.output(["rev-parse", "HEAD"], cwd=self.project_root)
        self.git.run(
            ["tag", "-a", tag, "-m", f"Release {version}"], cwd=self.project_root
        )
        tagged = self.git.output(
            ["rev-parse", f"{tag}^{{commit}}"], cwd=self.project_root
        )
        if tagged != commit:
            raise ReleaseError(f"tag {tag} does not point at release commit {commit}")

    def _reviewed_notes(self, version: str) -> str:
        """The section a reviewer approved for this version, published as the
        release body exactly as approved. Read before the build, so a missing
        section stops the release before anything is created."""
        changelog = self.project_root / NOTES_FILE
        if not changelog.is_file():
            raise ReleaseError(f"no {NOTES_FILE} to publish for {version}")
        notes = reviewed_section(changelog.read_text(encoding="utf-8"), version)
        if notes is None:
            raise ReleaseError(f"{NOTES_FILE} has no section for {version}")
        return notes

    def build_release(self, version: str, commit: str, *, dry_run: bool) -> Handoff:
        tag = self.manifest.tag(version)
        if dry_run:
            return Handoff(
                schema_version=1,
                product=self.manifest.name,
                repository=self.manifest.repository,
                version=version,
                tag=tag,
                commit=commit,
                source_url=self.manifest.asset_url(version),
                source_sha256="<dry-run>",
            )

        notes = self._reviewed_notes(version)
        # uv builds at the workspace root; the release asset is the package's.
        self.process.run(
            ["uv", "build", "--sdist", "--out-dir", str(self.project_root / "dist")],
            cwd=self.project_root,
        )
        asset = self.project_root / "dist" / self.manifest.asset_name(version)
        if not asset.is_file():
            raise ReleaseError(f"expected sdist not produced: {asset}")
        verify_sdist(asset, version)
        digest = self.hasher.sha256(asset.read_bytes())
        self.github.create_release(
            self.manifest.repository,
            tag,
            asset,
            f"{self.manifest.name} {version}",
            notes,
        )
        return Handoff(
            schema_version=1,
            product=self.manifest.name,
            repository=self.manifest.repository,
            version=version,
            tag=tag,
            commit=commit,
            source_url=self.manifest.asset_url(version),
            source_sha256=digest,
        )
