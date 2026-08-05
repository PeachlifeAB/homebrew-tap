from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from release_engine.manifest import load_manifest
from release_engine.models import Handoff, ReleaseError


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tap_root = Path(__file__).resolve().parents[1]

    def test_product_differences_are_manifest_data(self) -> None:
        sive = load_manifest(self.tap_root, "sive")
        bgtail = load_manifest(self.tap_root, "bgtail")

        self.assertEqual(sive.tag("1.2.3"), "v1.2.3")
        self.assertEqual(bgtail.tag("1.2.3"), "1.2.3")
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
            "PeachlifeAB/sive",
            "1.2.3",
            "v1.2.3",
            "a" * 40,
            "https://example.invalid/sive.tar.gz",
            "b" * 64,
        )

        self.assertEqual(Handoff.from_json(handoff.to_json()), handoff)


if __name__ == "__main__":
    unittest.main()
