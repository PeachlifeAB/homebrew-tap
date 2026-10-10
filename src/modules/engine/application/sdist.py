"""What a release sdist must look like before it is published."""

from __future__ import annotations

import tarfile
import tomllib
from pathlib import Path

from ..domain.models import ReleaseError


def verify_sdist(asset: Path, version: str) -> None:
    """Refuse an sdist with absolute paths or links, other than one
    `pyproject.toml`, or whose embedded version is not the release version."""
    with tarfile.open(asset, "r:gz") as archive:
        unsafe = [
            member.name
            for member in archive.getmembers()
            if member.name.startswith("/") or member.issym() or member.islnk()
        ]
        if unsafe:
            raise ReleaseError(f"sdist contains unsafe members: {', '.join(unsafe)}")
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
