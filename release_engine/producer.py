from __future__ import annotations

import re
import tarfile
import tempfile
from pathlib import Path

import tomllib

from .adapters import GitAdapter, GitHubAdapter, Sha256Hasher, SubprocessAdapter
from .models import Handoff, ProductManifest, ReleaseError, ReleaseObservation
from .observation import locked_version, observe_repository, project_version

_PROJECT_VERSION = re.compile(r'^version = "[^"]+"$', re.MULTILINE)


def _version_tuple(version: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


class ProducerRelease:
    def __init__(
        self,
        manifest: ProductManifest,
        project_root: Path,
        process: SubprocessAdapter,
        git: GitAdapter,
        github: GitHubAdapter,
    ) -> None:
        self.manifest = manifest
        self.project_root = project_root.resolve()
        self.process = process
        self.git = git
        self.github = github
        self.hasher = Sha256Hasher()

    def observe(self, version: str) -> ReleaseObservation:
        return observe_repository(
            self.manifest,
            self.project_root,
            self.git,
            self.github,
            version,
        )

    def require_release_start(
        self, observation: ReleaseObservation, version: str
    ) -> None:
        state = observation.repository
        if state.branch != "main":
            raise ReleaseError(f"release branch must be main, got {state.branch}")
        if state.dirty:
            raise ReleaseError("producer worktree is dirty:\n" + "\n".join(state.dirty))
        if not state.tracking:
            raise ReleaseError("producer main has no tracking branch")
        if state.ahead or state.behind:
            raise ReleaseError(
                f"producer differs from {state.tracking}: {state.ahead} ahead, {state.behind} behind"
            )
        if _version_tuple(version) <= _version_tuple(observation.declared_version):
            raise ReleaseError(
                f"release version {version} must exceed {observation.declared_version}"
            )
        if observation.local_tag_commit or observation.remote_tag_commit:
            raise ReleaseError(
                f"release tag already exists: {self.manifest.tag(version)}"
            )
        if observation.github_release_exists:
            raise ReleaseError(
                f"GitHub release already exists: {self.manifest.tag(version)}"
            )

    def prepare(self, version: str, *, dry_run: bool) -> None:
        observation = self.observe(version)
        self.require_release_start(observation, version)
        print(
            f"prepare {self.manifest.name} {observation.declared_version} -> {version}"
        )
        if dry_run:
            print(f"[dry-run] update pyproject.toml version to {version}")
            print("[dry-run] uv lock")
            print(f"[dry-run] task {self.manifest.quality_task}")
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
        self.process.run(["task", self.manifest.quality_task], cwd=self.project_root)
        self.verify_prepared(version)

    def verify_prepared(self, version: str) -> None:
        self.manifest.validate_version(version)
        declared = project_version(self.project_root)
        locked = locked_version(self.project_root, self.manifest.package)
        if declared != version or locked != version:
            raise ReleaseError(
                f"prepared version mismatch: requested={version}, pyproject={declared}, lock={locked}"
            )
        development_output = self.process.run(
            ["uv", "run", self.manifest.executable, "--version"],
            cwd=self.project_root,
            capture=True,
        )
        expected = f"{self.manifest.name} {version}"
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

    def commit_tag_push(self, version: str, *, dry_run: bool) -> str:
        self.verify_prepared(version)
        tag = self.manifest.tag(version)
        if dry_run:
            print("[dry-run] git add pyproject.toml uv.lock")
            print(f"[dry-run] git commit -m 'release: prepare {version}'")
            print(f"[dry-run] git tag -a {tag} -m 'Release {version}'")
            print(f"[dry-run] git push origin main {tag}")
            return "<dry-run>"

        self.git.run(["add", "pyproject.toml", "uv.lock"], cwd=self.project_root)
        self.git.run(
            ["commit", "-m", f"release: prepare {version}"], cwd=self.project_root
        )
        commit = self.git.output(["rev-parse", "HEAD"], cwd=self.project_root)
        if project_version(self.project_root) != version:
            raise ReleaseError("release commit does not contain prepared version")
        self.git.run(
            ["tag", "-a", tag, "-m", f"Release {version}"], cwd=self.project_root
        )
        tagged = self.git.output(
            ["rev-parse", f"{tag}^{{commit}}"], cwd=self.project_root
        )
        if tagged != commit:
            raise ReleaseError(f"tag {tag} does not point at release commit {commit}")
        self.git.run(["push", "origin", "main", tag], cwd=self.project_root)
        return commit

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

        self.process.run(["uv", "build", "--sdist"], cwd=self.project_root)
        asset = self.project_root / "dist" / self.manifest.asset_name(version)
        if not asset.is_file():
            raise ReleaseError(f"expected sdist not produced: {asset}")
        self._verify_sdist(asset, version)
        digest = self.hasher.sha256(asset.read_bytes())
        self.github.create_release(
            self.manifest.repository,
            tag,
            asset,
            f"{self.manifest.name} {version}",
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

    def _verify_sdist(self, asset: Path, version: str) -> None:
        with tarfile.open(asset, "r:gz") as archive:
            unsafe = [
                member.name
                for member in archive.getmembers()
                if member.name.startswith("/") or member.issym() or member.islnk()
            ]
            if unsafe:
                raise ReleaseError(
                    f"sdist contains unsafe members: {', '.join(unsafe)}"
                )
            names = [
                name for name in archive.getnames() if name.endswith("/pyproject.toml")
            ]
            if len(names) != 1:
                raise ReleaseError(
                    f"sdist must contain one pyproject.toml, found {len(names)}"
                )
            member = archive.extractfile(names[0])
            if member is None:
                raise ReleaseError("cannot read sdist pyproject.toml")
            embedded = str(tomllib.loads(member.read().decode())["project"]["version"])
        if embedded != version:
            raise ReleaseError(f"sdist version {embedded} != release {version}")
