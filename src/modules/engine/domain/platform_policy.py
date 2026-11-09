"""The tap's supported platforms, as one check every product is held to.

Apple Silicon macOS is supported, and Linux for portable products. Intel macOS is
not (Homebrew support tier 3, no new bottles). A product may narrow that set for
its own reasons and must never widen it.
"""

from __future__ import annotations

import re

from modules.engine.domain.models import CaskManifest, ProductManifest

# The forms Homebrew offers for declaring Intel support (Formula-Cookbook,
# "Handling different system configurations"; Cask-Cookbook, `depends_on arch`):
# a single arch symbol, an array of them (casks), an on_intel block, or an Intel
# branch in code.
_INTEL_ARCH = r":(?:x86_64|intel)\b"
_INTEL_FORMS = (
    re.compile(rf"depends_on\s+arch:\s*{_INTEL_ARCH}"),
    re.compile(rf"depends_on\s+arch:\s*\[[^\]]*{_INTEL_ARCH}[^\]]*\]"),
    re.compile(r"^\s*(on_intel)\b", re.MULTILINE),
    re.compile(r"Hardware::CPU\.intel\?"),
)


def intel_declarations(source: str) -> list[str]:
    """Each place a formula or cask declares Intel support, as written."""
    return [
        (match.group(1) if match.groups() else match.group(0)).strip()
        for form in _INTEL_FORMS
        for match in form.finditer(source)
    ]


def platform_summary(
    products: list[ProductManifest],
    casks: list[CaskManifest],
) -> str:
    """The one sentence the README must show for the declared platform set."""
    linux = sorted(product.name for product in products if not product.macos_only)
    macos = sorted(product.name for product in products if product.macos_only)
    macos.extend(sorted(cask.name for cask in casks))
    sentences = []
    if linux:
        sentences.append(f"{_names(linux)} also run on Linux")
    if macos:
        verb = "requires" if len(macos) == 1 else "require"
        sentences.append(f"{_names(macos)} {verb} macOS")
    return ". ".join(sentences) + "."


def _names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"
