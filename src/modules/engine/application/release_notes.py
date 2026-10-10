"""Release notes: one Keep a Changelog section per product.

The notes come from the commits that touched the product since its previous
release, rendered by git-cliff from the tap's `cliff.toml`, so the grouping and
the exclusion of maintenance commits live in that file and not in code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..domain.models import ProductManifest
from .ports import ProcessPort

# The reviewed release notes, one per product, next to its package.
NOTES_FILE = "CHANGELOG.md"


@dataclass(frozen=True)
class ReleaseNotes:
    section: str
    """This release's section only: the GitHub release body."""

    changelog: str
    """Header, section and comparison links: the product's CHANGELOG.md."""


def reviewed_section(changelog: str, version: str) -> str | None:
    """The section a reviewer approved for `version`, as the release body.

    It runs from the version's heading to the next release heading or to the
    comparison links, so older releases and the footer are never published with
    it. None when the changelog has no section for that version.
    """
    section = re.compile(
        rf"^## \[{re.escape(version)}\].*?(?=^## \[|^\[[^\]]+\]: |\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = section.search(changelog)
    return match.group(0).strip() if match else None


@dataclass(frozen=True)
class NotesSource:
    """Where the notes are rendered from."""

    repository: Path
    """The git repository holding the product's commits and tags."""

    config: Path
    """The `cliff.toml` that owns the format, grouping and exclusions."""

    repository_slug: str
    """`owner/name` on GitHub, for the comparison links."""


def render_release_notes(
    manifest: ProductManifest,
    version: str,
    source: NotesSource,
    process: ProcessPort,
) -> ReleaseNotes:
    """Render the notes for `version` from the product's unreleased commits.

    Only commits under the product's package directory since its previous tag
    are considered, and the previous tag is found by the product's tag prefix,
    so three products can share one repository and one tag space.
    """
    command = [
        "uv",
        "run",
        "--frozen",
        "--project",
        str(source.config.parent),
        "git-cliff",
        "--config",
        str(source.config),
        "--repository",
        str(source.repository),
        "--tag-pattern",
        f"^{re.escape(manifest.tag_prefix)}",
        "--include-path",
        f"packages/{manifest.package}/**",
        "--github-repo",
        source.repository_slug,
        "--tag",
        manifest.tag(version),
    ]
    # The section is only what this release adds; the changelog is the whole
    # history, which is what CHANGELOG.md must keep.
    return ReleaseNotes(
        section=process.run(
            [*command, "--unreleased", "--strip", "all"],
            cwd=source.repository,
            capture=True,
        ),
        changelog=process.run(command, cwd=source.repository, capture=True),
    )
