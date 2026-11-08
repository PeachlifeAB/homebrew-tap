import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from modules.engine.api.cask_platform_policy import main
from modules.engine.domain.models import CaskManifest, ReleaseError
from modules.engine.infrastructure.manifest import load_product


def test_generated_cask_matches_manifest_architectures() -> None:
    tap_root = Path(__file__).resolve().parents[1]
    product = load_product(tap_root, "hyprspace")
    assert isinstance(product, CaskManifest)
    cask_source = (tap_root / product.path).read_text(encoding="utf-8")
    architectures = product.supported_architectures
    assert architectures
    for architecture in architectures:
        assert f"depends_on arch: :{architecture}" in cask_source


@pytest.mark.parametrize("architecture", ["intel", "x86_64"])
def test_unsupported_architecture_is_rejected(
    tmp_path: Path, architecture: str
) -> None:
    tap_root = Path(__file__).resolve().parents[1]
    manifests = tmp_path / "release-products"
    manifests.mkdir()
    original = (tap_root / "release-products/hyprspace.toml").read_text(
        encoding="utf-8"
    )
    (manifests / "hyprspace.toml").write_text(
        original.replace('["arm64"]', f'["{architecture}"]'), encoding="utf-8"
    )
    output = io.StringIO()
    with (
        redirect_stdout(output),
        pytest.raises(ReleaseError, match="supported_architectures"),
    ):
        main(["--tap-root", str(tmp_path), "hyprspace"])
    assert output.getvalue() == ""


def test_arm64_restriction_is_rendered() -> None:
    tap_root = Path(__file__).resolve().parents[1]
    output = io.StringIO()
    with redirect_stdout(output):
        main(["--tap-root", str(tap_root), "hyprspace"])
    assert output.getvalue() == "  depends_on arch: :arm64\n"
