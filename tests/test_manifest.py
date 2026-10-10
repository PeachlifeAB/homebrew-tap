from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from modules.engine.domain.models import (
    CaskManifest,
    Handoff,
    ProductKind,
    ProductManifest,
    ReleaseError,
)
from modules.engine.infrastructure.manifest import load_manifest, load_product


class ProductKindTests(unittest.TestCase):
    """A manifest declares what kind of product it is, and a cask is not a formula
    with fields left blank: it has no package, tag, sdist or quality task."""

    def setUp(self) -> None:
        self.tap_root = Path(__file__).resolve().parents[1]

    def _manifest_dir(self, name: str, text: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "release-products").mkdir()
        (root / "release-products" / f"{name}.toml").write_text(text)
        return root

    def test_formula_manifests_declare_their_kind(self) -> None:
        for name in ("sive", "bgtail", "lgtvctrl"):
            with self.subTest(product=name):
                manifest = load_product(self.tap_root, name)

                self.assertIsInstance(manifest, ProductManifest)
                self.assertEqual(manifest.kind, ProductKind.FORMULA)

    def test_the_cask_manifest_loads_as_a_cask(self) -> None:
        manifest = load_product(self.tap_root, "hyprspace")

        assert isinstance(manifest, CaskManifest)
        self.assertEqual(manifest.kind, ProductKind.CASK)
        self.assertEqual(manifest.cask, "hyprspace")

    def test_a_cask_announcement_links_the_upstream_notes_for_the_version(self) -> None:
        manifest = load_product(self.tap_root, "hyprspace")
        assert isinstance(manifest, CaskManifest)

        self.assertEqual(
            manifest.release_notes_url("0.5.0"),
            "https://github.com/PeachlifeAB/hyprspace-releases/releases/tag/v0.5.0",
        )

    def test_loading_a_cask_as_a_formula_is_refused(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "hyprspace is a cask"):
            load_manifest(self.tap_root, "hyprspace")

    def test_a_manifest_without_a_kind_is_rejected(self) -> None:
        source = (self.tap_root / "release-products" / "sive.toml").read_text()
        root = self._manifest_dir("sive", source.replace('kind = "formula"\n', ""))

        with self.assertRaisesRegex(ReleaseError, "kind"):
            load_product(root, "sive")

    def test_an_unknown_kind_is_rejected(self) -> None:
        source = (self.tap_root / "release-products" / "sive.toml").read_text()
        root = self._manifest_dir("sive", source.replace('formula"', 'font"', 1))

        with self.assertRaisesRegex(ReleaseError, "unknown kind"):
            load_product(root, "sive")

    def test_a_cask_manifest_may_not_carry_formula_fields(self) -> None:
        source = (self.tap_root / "release-products" / "hyprspace.toml").read_text()
        root = self._manifest_dir("hyprspace", source + 'package = "hyprspace"\n')

        with self.assertRaisesRegex(ReleaseError, "unknown keys: package"):
            load_product(root, "hyprspace")


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tap_root = Path(__file__).resolve().parents[1]

    def test_product_differences_are_manifest_data(self) -> None:
        sive = load_manifest(self.tap_root, "sive")
        bgtail = load_manifest(self.tap_root, "bgtail")

        self.assertEqual(sive.tag("1.2.3"), "sive-1.2.3")
        self.assertEqual(bgtail.tag("1.2.3"), "bgtail-1.2.3")
        self.assertEqual(sive.asset_name("1.2.3"), "sive-1.2.3.tar.gz")
        self.assertEqual(bgtail.asset_name("1.2.3"), "bgtail-1.2.3.tar.gz")

    def test_manifest_rejects_mutable_release_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            products = root / "release-products"
            products.mkdir()
            source = (self.tap_root / "release-products" / "sive.toml").read_text()
            (products / "sive.toml").write_text(source + 'version = "1.2.3"\n')

            with self.assertRaisesRegex(ReleaseError, "mutable state"):
                load_manifest(root, "sive")

    def test_a_release_watches_every_repository_behind_every_product(self) -> None:
        """A Dependabot update in any of them blocks a release of any product."""
        from modules.engine.infrastructure.manifest import owned_repositories

        self.assertEqual(
            owned_repositories(self.tap_root),
            (
                "PeachlifeAB/homebrew-tap",
                "PeachlifeAB/hyprspace-core",
                "PeachlifeAB/hyprspace-releases",
            ),
        )

    def test_handoff_round_trip(self) -> None:
        handoff = Handoff(
            1,
            "sive",
            "PeachlifeAB/homebrew-tap",
            "1.2.3",
            "sive-v1.2.3",
            "a" * 40,
            "https://example.invalid/sive.tar.gz",
            "b" * 64,
        )

        self.assertEqual(Handoff.from_json(handoff.to_json()), handoff)


class ReleasableProductTests(unittest.TestCase):
    """A manifest is what makes a product releasable, so the CLI must offer
    exactly the products that have one. Listing them as literals let lgtvctrl
    gain a manifest without becoming selectable."""

    def test_every_manifest_is_selectable(self) -> None:
        # Read the parser's own choices, not the helper that feeds it:
        # asserting the helper against the directory it globs proves nothing.
        from modules.engine.api.cli import build_parser

        root = Path(__file__).resolve().parents[1]
        manifests = sorted(
            path.stem for path in (root / "release-products").glob("*.toml")
        )
        product = next(
            action for action in build_parser()._actions if action.dest == "product"
        )
        self.assertIsNotNone(product.choices, "--product offers no choices")
        assert product.choices is not None
        self.assertEqual(manifests, sorted(product.choices))

    def test_repo_state_reports_every_product(self) -> None:
        """bin/repo-state listed two products as literals, so lgtvctrl went
        unreported. It reads the manifests now, executable name included —
        lgtvctrl installs `tv`, not `lgtvctrl`."""
        root = Path(__file__).resolve().parents[1]
        script = (root / "bin" / "repo-state").read_text(encoding="utf-8")
        self.assertIn('"$REPO"/release-products/*.toml', script)
        for product in ("sive", "bgtail", "lgtvctrl"):
            self.assertNotIn(
                f"for product in {product}",
                script,
                "products must come from the manifests, not a literal list",
            )


if __name__ == "__main__":
    unittest.main()
