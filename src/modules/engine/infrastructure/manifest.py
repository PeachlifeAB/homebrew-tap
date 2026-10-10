from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from ..domain.models import (
    CaskManifest,
    Product,
    ProductKind,
    ProductManifest,
    ReleaseError,
)

QUALITY_TASK = "test"
VERSION_PLACEHOLDER = "{version}"
KIND_KEY = "kind"

_COMMON_KEYS = {"schema_version", KIND_KEY, "name", "repository"}
_FORMULA_KEYS = _COMMON_KEYS | {
    "formula",
    "executable",
    "package",
    "tag_prefix",
    "asset_template",
    "quality_task",
    "smoke_args",
    "macos_only",
}
_CASK_KEYS = _COMMON_KEYS | {"source_repository", "cask", "release_notes_template"}
_KEYS_BY_KIND = {ProductKind.FORMULA: _FORMULA_KEYS, ProductKind.CASK: _CASK_KEYS}
_MUTABLE_KEYS = {
    "version",
    "commit",
    "sha256",
    "pull_request",
    "workflow_run",
    "bottle_tag",
}


def _validate_keys(keys: set[str], allowed: set[str]) -> None:
    """Reject mutable, unknown or missing manifest keys."""
    forbidden = keys & _MUTABLE_KEYS
    unknown = keys - allowed
    missing = allowed - keys
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


def _read(tap_root: Path, product: str) -> dict[str, Any]:
    path = tap_root / "release-products" / f"{product}.toml"
    if not path.is_file():
        raise ReleaseError(f"unknown product manifest: {path}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _kind(data: dict[str, Any]) -> ProductKind:
    if KIND_KEY not in data:
        raise ReleaseError(f"manifest is missing keys: {KIND_KEY}")
    try:
        return ProductKind(data[KIND_KEY])
    except ValueError:
        known = ", ".join(kind.value for kind in ProductKind)
        raise ReleaseError(
            f"manifest has unknown {KIND_KEY} {data[KIND_KEY]!r}; "
            f"expected one of: {known}"
        ) from None


def _formula(data: dict[str, Any]) -> ProductManifest:
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


def _cask(data: dict[str, Any]) -> CaskManifest:
    if VERSION_PLACEHOLDER not in data["release_notes_template"]:
        raise ReleaseError(
            f"manifest release_notes_template must contain {VERSION_PLACEHOLDER}"
        )
    return CaskManifest(
        schema_version=data["schema_version"],
        name=data["name"],
        repository=data["repository"],
        source_repository=data["source_repository"],
        cask=data["cask"],
        release_notes_template=data["release_notes_template"],
    )


def load_product(tap_root: Path, product: str) -> Product:
    """The manifest of a formula or a cask, whichever `kind` it declares."""
    data = _read(tap_root, product)
    kind = _kind(data)
    _validate_keys(set(data), _KEYS_BY_KIND[kind])
    if data["schema_version"] != 1:
        raise ReleaseError(f"unsupported manifest schema: {data['schema_version']}")
    return _formula(data) if kind is ProductKind.FORMULA else _cask(data)


def owned_repositories(tap_root: Path) -> tuple[str, ...]:
    """Every GitHub repository behind a product the tap ships: where each is
    released from and, for a cask, where it is built."""
    products = [
        load_product(tap_root, path.stem)
        for path in sorted((tap_root / "release-products").glob("*.toml"))
    ]
    repositories = {product.repository for product in products} | {
        product.source_repository
        for product in products
        if isinstance(product, CaskManifest)
    }
    return tuple(sorted(repositories))


def load_manifest(tap_root: Path, product: str) -> ProductManifest:
    """A formula's manifest; a cask has its own shape and is refused here."""
    manifest = load_product(tap_root, product)
    if not isinstance(manifest, ProductManifest):
        raise ReleaseError(f"{product} is a cask, not a formula")
    return manifest
