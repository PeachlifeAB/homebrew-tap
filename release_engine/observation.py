from __future__ import annotations

import re
import subprocess
from pathlib import Path

import tomllib

from .adapters import GitAdapter, GitHubAdapter
from .models import ProductManifest, ReleaseError, ReleaseObservation, RepositoryState

_LOCK_PACKAGE = re.compile(
    r'\[\[package\]\]\nname = "(?P<name>[^"]+)"\nversion = "(?P<version>[^"]+)"'
)


def project_version(project_root: Path) -> str:
    path = project_root / "pyproject.toml"
    try:
        return str(
            tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]
        )
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError) as error:
        raise ReleaseError(
            f"cannot read project version from {path}: {error}"
        ) from error


def locked_version(project_root: Path, package: str) -> str:
    path = project_root / "uv.lock"
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ReleaseError(f"lockfile not found: {path}") from error
    for match in _LOCK_PACKAGE.finditer(content):
        if match.group("name") == package:
            return match.group("version")
    raise ReleaseError(f"package {package!r} not found in {path}")


def observe_repository(
    manifest: ProductManifest,
    project_root: Path,
    git: GitAdapter,
    github: GitHubAdapter,
    version: str,
) -> ReleaseObservation:
    manifest.validate_version(version)
    branch = git.output(["rev-parse", "--abbrev-ref", "HEAD"], cwd=project_root)
    head = git.output(["rev-parse", "HEAD"], cwd=project_root)
    dirty = tuple(
        line
        for line in git.output(["status", "--porcelain"], cwd=project_root).splitlines()
        if line
    )
    try:
        tracking = git.output(
            ["rev-parse", "--abbrev-ref", "@{upstream}"], cwd=project_root
        )
        ahead, behind = (
            int(value)
            for value in git.output(
                ["rev-list", "--left-right", "--count", f"{tracking}...HEAD"],
                cwd=project_root,
            ).split()
        )
        # rev-list prints tracking-only first, HEAD-only second.
        ahead, behind = behind, ahead
    except subprocess.CalledProcessError:
        tracking, ahead, behind = "", 0, 0

    tag = manifest.tag(version)
    try:
        local_tag_commit = git.output(
            ["rev-parse", f"{tag}^{{commit}}"], cwd=project_root
        )
    except subprocess.CalledProcessError:
        local_tag_commit = None

    return ReleaseObservation(
        product=manifest,
        repository=RepositoryState(
            branch=branch,
            head=head,
            tracking=tracking,
            ahead=ahead,
            behind=behind,
            dirty=dirty,
        ),
        declared_version=project_version(project_root),
        locked_version=locked_version(project_root, manifest.package),
        local_tag_commit=local_tag_commit,
        remote_tag_commit=github.tag_commit(manifest.repository, tag),
        github_release_exists=github.release_exists(manifest.repository, tag),
    )


def print_observation(observation: ReleaseObservation) -> None:
    state = observation.repository
    print(f"product: {observation.product.name}")
    print(f"branch: {state.branch} @ {state.head}")
    print(
        f"tracking: {state.tracking or '<none>'} ({state.ahead} ahead, {state.behind} behind)"
    )
    print(f"dirty: {len(state.dirty)}")
    for line in state.dirty:
        print(f"  {line}")
    print(f"pyproject version: {observation.declared_version}")
    print(f"uv.lock version: {observation.locked_version}")
    print(f"local tag commit: {observation.local_tag_commit or '<none>'}")
    print(f"remote tag commit: {observation.remote_tag_commit or '<none>'}")
    print(
        f"GitHub release: {'present' if observation.github_release_exists else 'absent'}"
    )
