"""The cheap, local gates every release starts with: repository state only.

One small function per check, each raising ReleaseError with the message the
operator needs; `start_gates` lists them so the ladder can order and run them.
"""

from __future__ import annotations

import tomllib
from functools import partial
from pathlib import Path

from ..domain.models import (
    ProductManifest,
    ReleaseError,
    ReleaseObservation,
    RepositoryState,
)
from .gates import Gate, GateCost
from .observation import changed_paths
from .release_notes import NOTES_FILE

RELEASE_BRANCH = "main"


def _version_tuple(version: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


def _declared_project_name(project_root: Path) -> str:
    try:
        text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
        return str(tomllib.loads(text)["project"]["name"])
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError):
        return "<none>"


def _require_package_root(manifest: ProductManifest, project_root: Path) -> None:
    """`prepare` edits <project-root>/pyproject.toml while reads look in
    packages/<name>/ first, so the tap root passes a dry run and then edits the
    wrong file in a real one."""
    declared = _declared_project_name(project_root)
    if declared != manifest.package:
        raise ReleaseError(
            f"use --project-root packages/{manifest.package}: "
            f"{project_root / 'pyproject.toml'} declares {declared!r}, not "
            f"{manifest.package!r}, and prepare edits that file"
        )


def _require_release_branch(state: RepositoryState) -> None:
    if state.branch != RELEASE_BRANCH:
        raise ReleaseError(
            f"release branch must be {RELEASE_BRANCH}, got {state.branch}"
        )


def _require_clean_worktree(state: RepositoryState, reviewed_notes: str) -> None:
    """The reviewed notes are the one change a release may start with: `notes`
    writes them for review and the prepare commit carries them."""
    others = [path for path in changed_paths(state.dirty) if path != reviewed_notes]
    if others:
        raise ReleaseError("producer worktree is dirty:\n" + "\n".join(others))


def _require_no_dependabot_branches(state: RepositoryState) -> None:
    """An open dependency update is decided before a release, so a release
    never ships on dependencies a pending pull request already replaces."""
    if state.dependabot_branches:
        raise ReleaseError(
            "Dependabot PR detected and must be handled before release: "
            + ", ".join(state.dependabot_branches)
            + " (merge its PR when green; when red, get approval to resolve it)"
        )


def _require_tracking_branch(state: RepositoryState) -> None:
    if not state.tracking:
        raise ReleaseError("producer main has no tracking branch")


def _require_synced(state: RepositoryState) -> None:
    if state.ahead or state.behind:
        raise ReleaseError(
            f"producer differs from {state.tracking}: "
            f"{state.ahead} ahead, {state.behind} behind"
        )


def _require_version_increase(declared: str, version: str) -> None:
    if _version_tuple(version) <= _version_tuple(declared):
        raise ReleaseError(f"release version {version} must exceed {declared}")


def _require_free_tag(observation: ReleaseObservation, tag: str) -> None:
    if observation.local_tag_commit or observation.remote_tag_commit:
        raise ReleaseError(f"release tag already exists: {tag}")


def _require_free_release(observation: ReleaseObservation, tag: str) -> None:
    if observation.github_release_exists:
        raise ReleaseError(f"GitHub release already exists: {tag}")


def state_gates(state: RepositoryState) -> tuple[Gate, ...]:
    """Where the checkout stands against its upstream. Formula and cask releases
    both start from the same three checks, so they share this one definition."""
    checks = (
        ("no-dependabot-branches", partial(_require_no_dependabot_branches, state)),
        ("release-branch", partial(_require_release_branch, state)),
        ("tracking-branch", partial(_require_tracking_branch, state)),
        ("synced-with-remote", partial(_require_synced, state)),
    )
    return tuple(Gate(name, GateCost.INSTANT, run) for name, run in checks)


def start_gates(
    manifest: ProductManifest,
    project_root: Path,
    observation: ReleaseObservation,
    version: str,
) -> tuple[Gate, ...]:
    state = observation.repository
    tag = manifest.tag(version)
    checks = (
        (
            "project-root-is-package",
            partial(_require_package_root, manifest, project_root),
        ),
        (
            "clean-worktree",
            partial(
                _require_clean_worktree,
                state,
                f"packages/{manifest.package}/{NOTES_FILE}",
            ),
        ),
        (
            "version-increases",
            partial(_require_version_increase, observation.declared_version, version),
        ),
        ("tag-is-free", partial(_require_free_tag, observation, tag)),
        ("github-release-is-free", partial(_require_free_release, observation, tag)),
    )
    return (
        *state_gates(state),
        *(Gate(name, GateCost.INSTANT, run) for name, run in checks),
    )
