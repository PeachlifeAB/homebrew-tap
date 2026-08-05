from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class ReleaseError(RuntimeError):
    """Raised when observed release state violates a safety invariant."""


@dataclass(frozen=True)
class ProductManifest:
    schema_version: int
    name: str
    repository: str
    formula: str
    executable: str
    package: str
    tag_prefix: str
    asset_template: str
    quality_task: str
    smoke_args: tuple[str, ...]
    macos_only: bool

    def validate_version(self, version: str) -> None:
        if not VERSION_PATTERN.fullmatch(version):
            raise ReleaseError(f"invalid release version: {version!r}")

    def tag(self, version: str) -> str:
        self.validate_version(version)
        return f"{self.tag_prefix}{version}"

    def asset_name(self, version: str) -> str:
        self.validate_version(version)
        return self.asset_template.format(name=self.name, version=version)

    def asset_url(self, version: str) -> str:
        return (
            f"https://github.com/{self.repository}/releases/download/"
            f"{self.tag(version)}/{self.asset_name(version)}"
        )


@dataclass(frozen=True)
class Handoff:
    schema_version: int
    product: str
    repository: str
    version: str
    tag: str
    commit: str
    source_url: str
    source_sha256: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, raw: str) -> Handoff:
        try:
            data = json.loads(raw)
            return cls(**data)
        except (TypeError, ValueError) as error:
            raise ReleaseError(f"invalid handoff: {error}") from error


@dataclass(frozen=True)
class RepositoryState:
    branch: str
    head: str
    tracking: str
    ahead: int
    behind: int
    dirty: tuple[str, ...]


@dataclass(frozen=True)
class ReleaseObservation:
    product: ProductManifest
    repository: RepositoryState
    declared_version: str
    locked_version: str
    local_tag_commit: str | None
    remote_tag_commit: str | None
    github_release_exists: bool
