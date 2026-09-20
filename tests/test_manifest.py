from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from modules.engine.domain.models import Handoff, ReleaseError
from modules.engine.infrastructure.manifest import load_manifest


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
