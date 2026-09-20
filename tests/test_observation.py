"""The release engine resolves versions from the workspace it runs in.

`locked_version` must work for both layouts the engine meets: a standalone
package with its own uv.lock, and a uv workspace member whose only lockfile
lives at the workspace root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.engine.application.observation import locked_version, project_version
from modules.engine.domain.models import ReleaseError

LOCK = '[[package]]\nname = "sive"\nversion = "0.1.8"\n'


def _write_lock(directory: Path, content: str = LOCK) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "uv.lock").write_text(content, encoding="utf-8")


class TestLockedVersion:
    def test_reads_the_packages_own_lockfile(self, tmp_path: Path) -> None:
        _write_lock(tmp_path)

        assert locked_version(tmp_path, "sive") == "0.1.8"

    def test_walks_up_to_the_workspace_lock(self, tmp_path: Path) -> None:
        """A workspace member has no uv.lock of its own; the root does."""
        _write_lock(tmp_path)
        member = tmp_path / "packages" / "sive"
        member.mkdir(parents=True)

        assert locked_version(member, "sive") == "0.1.8"

    def test_the_nearest_lockfile_wins(self, tmp_path: Path) -> None:
        _write_lock(tmp_path, '[[package]]\nname = "sive"\nversion = "9.9.9"\n')
        member = tmp_path / "packages" / "sive"
        _write_lock(member)

        assert locked_version(member, "sive") == "0.1.8"

    def test_missing_lockfile_names_the_search_start(self, tmp_path: Path) -> None:
        member = tmp_path / "packages" / "sive"
        member.mkdir(parents=True)

        with pytest.raises(ReleaseError, match="lockfile"):
            locked_version(member, "sive")

    def test_package_absent_from_the_lockfile(self, tmp_path: Path) -> None:
        _write_lock(tmp_path)

        with pytest.raises(ReleaseError, match="not found"):
            locked_version(tmp_path, "bgtail")


class TestProjectVersion:
    """The mirror image of `locked_version`, and the direction is the point.

    The lockfile is found by walking UP, because a uv workspace shares one at
    its root. A version must be read DOWN, at the member's own pyproject:
    "each package defines its own pyproject.toml, but the workspace shares a
    single lockfile". The root's version does not apply to its members.

    `bin/release --project-root .` passes the repository root, so reading
    `project_root / "pyproject.toml"` yields the workspace container's
    placeholder rather than the product's real version.
    """

    def _write_project(self, directory: Path, name: str, version: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "{version}"\n', encoding="utf-8"
        )

    def test_reads_the_packages_own_version_not_the_workspace_roots(
        self, tmp_path: Path
    ) -> None:
        self._write_project(tmp_path, "homebrew-tap", "0.1.0")
        self._write_project(tmp_path / "packages" / "sive", "sive", "0.1.8")

        assert project_version(tmp_path, "sive") == "0.1.8"

    def test_reads_a_standalone_package_in_place(self, tmp_path: Path) -> None:
        """A package that is its own project root, with no packages/ below."""
        self._write_project(tmp_path, "sive", "0.1.8")

        assert project_version(tmp_path, "sive") == "0.1.8"

    def test_missing_version_names_the_file_it_read(self, tmp_path: Path) -> None:
        self._write_project(tmp_path, "homebrew-tap", "0.1.0")
        member = tmp_path / "packages" / "sive"
        member.mkdir(parents=True)
        (member / "pyproject.toml").write_text('[project]\nname = "sive"\n')

        with pytest.raises(ReleaseError, match="cannot read project version"):
            project_version(tmp_path, "sive")
