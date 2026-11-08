from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from ..domain.models import CaskManifest, ReleaseError
from ..infrastructure.manifest import load_product


def main(argv: list[str] | None = None) -> None:
    parser = ArgumentParser(
        description="Render manifest-owned cask architecture restrictions"
    )
    parser.add_argument("product")
    parser.add_argument("--tap-root", type=Path, required=True)
    args = parser.parse_args(argv)
    product = load_product(args.tap_root, args.product)
    if not isinstance(product, CaskManifest):
        raise ReleaseError("platform policy requires a cask manifest")
    architectures = [f":{value}" for value in product.supported_architectures]
    restriction = (
        architectures[0] if len(architectures) == 1 else f"[{', '.join(architectures)}]"
    )
    print(f"  depends_on arch: {restriction}")


if __name__ == "__main__":
    main()
