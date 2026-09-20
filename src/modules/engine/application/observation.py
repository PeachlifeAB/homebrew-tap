from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ..domain.models import (
    CommandFailed,
    ProductManifest,
    ReleaseError,
    ReleaseObservation,
    RepositoryState,
)
from .ports import GitHubPort, GitPort

_LOCK_PACKAGE = re.compile(
    r'\[\[package\]\]\nname = "(?P<name>[^"]+)"\nversion = "(?P<version>[^"]+)"'
)


def project_path(project_root: Path, package: str) -> Path:
    """The pyproject declaring `package`'s version.

    The mirror image of `lock_path`, and the direction is the point. A uv
    workspace shares one lockfile at its root, so a lock is found by walking
    UP; but "each package defines its own pyproject.toml", so a version is
    read DOWN, at the member's own file. The workspace root's version belongs
    to the container and says nothing about its members.

    A standalone package is its own project root and keeps both in place,
    which the members-first order still resolves correctly.
    """
    member = project_root / "packages" / package / "pyproject.toml"
    return member if member.is_file() else project_root / "pyproject.toml"


def project_version(project_root: Path, package: str) -> str:
    path = project_path(project_root, package)
    try:
        return str(
            tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]
        )
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError) as error:
        raise ReleaseError(
            f"cannot read project version from {path}: {error}"
        ) from error


def lock_path(project_root: Path) -> Path:
    """The nearest uv.lock at or above the package directory.

    A uv workspace member has no lockfile of its own; the single lock lives
    at the workspace root. A standalone package keeps its own, which the
    nearest-first walk still finds in its own directory.
    """
    for directory in (project_root, *project_root.parents):
        candidate = directory / "uv.lock"
        if candidate.is_file():
            return candidate
    raise ReleaseError(f"lockfile not found at or above: {project_root}")


def locked_version(project_root: Path, package: str) -> str:
    path = lock_path(project_root)
    content = path.read_text(encoding="utf-8")
    for match in _LOCK_PACKAGE.finditer(content):
        if match.group("name") == package:
            return match.group("version")
    raise ReleaseError(f"package {package!r} not found in {path}")


def observe_repository(
    manifest: ProductManifest,
    project_root: Path,
    git: GitPort,
    github: GitHubPort,
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
    except CommandFailed:
        tracking, ahead, behind = "", 0, 0

    tag = manifest.tag(version)
    try:
        local_tag_commit = git.output(
            ["rev-parse", f"{tag}^{{commit}}"], cwd=project_root
        )
    except CommandFailed:
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
        declared_version=project_version(project_root, manifest.package),
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
        f"tracking: {state.tracking or '<none>'} "
        f"({state.ahead} ahead, {state.behind} behind)"
    )
    print(f"dirty: {len(state.dirty)}")
    for line in state.dirty:
        print(f"  {line}")
    print(f"pyproject version: {observation.declared_version}")
    print(f"uv.lock version: {observation.locked_version}")
    print(f"local tag commit: {observation.local_tag_commit or '<none>'}")
    print(f"remote tag commit: {observation.remote_tag_commit or '<none>'}")
    print(
        "GitHub release: "
        f"{'present' if observation.github_release_exists else 'absent'}"
    )
