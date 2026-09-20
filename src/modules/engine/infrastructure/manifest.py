from __future__ import annotations

import tomllib
from pathlib import Path

from ..domain.models import ProductManifest, ReleaseError

QUALITY_TASK = "test"
VERSION_PLACEHOLDER = "{version}"

_ALLOWED_KEYS = {
    "schema_version",
    "name",
    "repository",
    "formula",
    "executable",
    "package",
    "tag_prefix",
    "asset_template",
    "quality_task",
    "smoke_args",
    "macos_only",
}
_REQUIRED_KEYS = _ALLOWED_KEYS
_MUTABLE_KEYS = {
    "version",
    "commit",
    "sha256",
    "pull_request",
    "workflow_run",
    "bottle_tag",
}


def _validate_keys(keys: set[str]) -> None:
    """Reject mutable, unknown or missing manifest keys."""
    forbidden = keys & _MUTABLE_KEYS
    unknown = keys - _ALLOWED_KEYS
    missing = _REQUIRED_KEYS - keys
    if forbidden:
        raise ReleaseError(
            f"manifest contains mutable state: {', '.join(sorted(forbidden))}"
        )
    if unknown:
        raise ReleaseError(
            f"manifest contains unknown keys: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise ReleaseError(f"manifest is missing keys: {', '.join(sorted(missing))}")


def load_manifest(tap_root: Path, product: str) -> ProductManifest:
    path = tap_root / "release-products" / f"{product}.toml"
    if not path.is_file():
        raise ReleaseError(f"unknown product manifest: {path}")

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    _validate_keys(set(data))

    if data["schema_version"] != 1:
        raise ReleaseError(f"unsupported manifest schema: {data['schema_version']}")
    if not isinstance(data["smoke_args"], list) or not all(
        isinstance(value, str) for value in data["smoke_args"]
    ):
        raise ReleaseError("manifest smoke_args must be a string array")
    if data["quality_task"] != QUALITY_TASK:
        raise ReleaseError(
            f"manifest quality_task must name the owner task '{QUALITY_TASK}'"
        )
    if VERSION_PLACEHOLDER not in data["asset_template"]:
        raise ReleaseError(
            f"manifest asset_template must contain {VERSION_PLACEHOLDER}"
        )

    return ProductManifest(
        schema_version=data["schema_version"],
        name=data["name"],
        repository=data["repository"],
        formula=data["formula"],
        executable=data["executable"],
        package=data["package"],
        tag_prefix=data["tag_prefix"],
        asset_template=data["asset_template"],
        quality_task=data["quality_task"],
        smoke_args=tuple(data["smoke_args"]),
        macos_only=data["macos_only"],
    )
