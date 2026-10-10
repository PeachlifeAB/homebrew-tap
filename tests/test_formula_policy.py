from __future__ import annotations

import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from modules.engine.domain.models import CaskManifest, ProductManifest
from modules.engine.domain.platform_policy import intel_declarations

# A formula's livecheck block, indented two spaces at the top level of the
# class body. `{2}` rather than two literal spaces, which read as one.
_LIVECHECK_BLOCK = re.compile(
    r"^ {2}livecheck do\n(.*?)^ {2}end$", re.DOTALL | re.MULTILINE
)

# The one definition of the Python the tap ships and tests on.
TAP_PYTHON_FILE = ".python-version"

# Formulae whose published bottle was built on an older Python. Each entry goes
# when homebrew-tap-pvg.2 rebuilds that bottle on the tap Python; a formula
# moved without its rebuild would pour a venv whose Python is no longer a
# dependency.
PYTHON_MIGRATION_PENDING = {"bgtail": "3.13", "lgtvctrl": "3.13"}


class FormulaPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_every_python_formula_installs_through_the_virtualenv_helper(self) -> None:
        """Install into one venv the way homebrew-core does: 669 formulae to 0
        across the corpus.

        Installing with `uv pip install --no-deps` works only while a package
        has no runtime dependencies; the first one it gains yields a broken
        install rather than a build failure. Held for all three formulae
        because scoping this to one is how the version assertion drifted. Which
        Python each formula builds on is its manifest's `python`, checked by
        `test_the_formula_builds_on_the_python_its_manifest_declares`.
        """
        for formula in ("sive", "bgtail", "lgtvctrl"):
            with self.subTest(formula=formula):
                content = (self.root / f"Formula/{formula}.rb").read_text()
                self.assertIn("include Language::Python::Virtualenv", content)
                self.assertNotIn('depends_on "uv"', content)
                self.assertNotIn("uv pip install", content)

        # Every formula installs its whole resource set into one venv, then
        # builds itself against that venv. `build_isolation: false` is what
        # makes the vendored setuptools reachable: pip's isolated build env is
        # empty and the sandbox has no network, so an isolated build cannot
        # find any backend. This is `aws-sam-cli`'s shape, and 14 other core
        # formulae build offline the same way.
        for formula in ("sive", "bgtail", "lgtvctrl"):
            with self.subTest(formula=formula):
                content = (self.root / f"Formula/{formula}.rb").read_text()
                self.assertIn("virtualenv_create(libexec", content)
                code = [
                    line
                    for line in content.splitlines()
                    if not line.lstrip().startswith("#")
                ]
                self.assertTrue(
                    any("build_isolation: false" in line for line in code),
                    "the package must build against the venv, not an empty "
                    "isolated env the sandbox cannot populate",
                )

        self.assertNotIn(
            "setuptools-scm", (self.root / "Formula/lgtvctrl.rb").read_text()
        )

    def test_no_formula_pins_a_python_abi_wheel(self) -> None:
        """A cp313 wheel pins the formula to one Python ABI and cannot be
        staged as a resource, which is why lgtvctrl hand-drove its venv.

        Every pyobjc-dependent formula in homebrew-core declares sdists; all
        three pyobjc packages build from source here, verified by a from-source
        install of lgtvctrl.
        """
        for formula in ("sive", "bgtail", "lgtvctrl"):
            with self.subTest(formula=formula):
                content = (self.root / f"Formula/{formula}.rb").read_text()
                wheels = [
                    line.strip()
                    for line in content.splitlines()
                    if ".whl" in line and "url" in line
                ]
                self.assertEqual(
                    [], wheels, f"{formula} pins a wheel instead of an sdist"
                )

    def test_every_package_backend_is_vendored_by_its_formula(self) -> None:
        """A Homebrew build has no network and its python vendors only pip and
        wheel, so an isolated build cannot fetch the backend named in
        `[build-system] requires`. Verified offline: setuptools and uv_build
        both fail without it, and a PyPI sdist is not exempt — PKG-INFO does
        not stop pip honouring the requirement.

        homebrew-core vendors setuptools in 77 formulae and uv_build in none.
        """
        for formula, package in (
            ("sive", "sive"),
            ("bgtail", "bgtail"),
            ("lgtvctrl", "lgtvctrl"),
        ):
            with self.subTest(formula=formula):
                pyproject = (
                    self.root / f"packages/{package}/pyproject.toml"
                ).read_text()
                self.assertIn(
                    "setuptools.build_meta",
                    pyproject,
                    "no formula in homebrew-core vendors a uv_build backend",
                )
                content = (self.root / f"Formula/{formula}.rb").read_text()
                self.assertIn(
                    'resource "setuptools"',
                    content,
                    f"{formula} builds from source but never vendors its backend",
                )

    def test_every_formula_asserts_the_full_version_string(self) -> None:
        """Any assert_match on the version passes against `0.1.1.dev+...`.

        A hardcoded literal and `version.to_s` are both substrings, so require
        assert_equal on the version line rather than banning one spelling.
        """
        for formula in ("sive", "bgtail", "lgtvctrl"):
            with self.subTest(formula=formula):
                content = (self.root / f"Formula/{formula}.rb").read_text()
                version_asserts = [
                    line.strip()
                    for line in content.splitlines()
                    if "--version" in line and "assert" in line
                ]
                self.assertTrue(version_asserts, f"{formula} never asserts its version")
                for line in version_asserts:
                    self.assertTrue(
                        line.startswith("assert_equal"),
                        f"{formula}: {line!r} is a substring check, which passes "
                        "against a dev-suffixed build",
                    )

    def test_no_formula_test_block_stops_at_the_version_string(self) -> None:
        """`--version` imports only the stdlib on all three, so a version-only
        test passes on an install with every dependency missing.

        Corpus: 582 of 600 sampled core formulae exercise real behaviour and
        1,476 start a real process in `test do`; only 18 stop at `--version`.
        Each test must therefore run the program and load a dependency the
        formula installs, and bound anything it starts so a hang fails.
        """
        for formula in ("sive", "bgtail", "lgtvctrl"):
            with self.subTest(formula=formula):
                block = self._test_block(formula)
                self.assertTrue(
                    any(
                        dep in block
                        for dep in ("cryptography", "bscpylgtv", "snapshot_crypto")
                    )
                    or "spawn" in block,
                    f"{formula}: test only proves the stdlib works",
                )
                self.assertIn(
                    "Timeout.timeout",
                    block,
                    f"{formula}: an unbounded test blocks the release on a hang",
                )

    def _test_block(self, formula: str) -> str:
        """The formula's `test do` body, excluding comments."""
        lines = (self.root / f"Formula/{formula}.rb").read_text().splitlines()
        start = next(i for i, line in enumerate(lines) if line.strip() == "test do")
        end = next(i for i in range(start + 1, len(lines)) if lines[i] == "  end")
        return "\n".join(
            line for line in lines[start:end] if not line.lstrip().startswith("#")
        )


class ManifestPolicyTests(unittest.TestCase):
    """Manifests and formulae must not drift apart."""

    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(self.root / "src"))

    def _products(self) -> list[ProductManifest | CaskManifest]:
        from modules.engine.infrastructure.manifest import load_product

        return [
            load_product(self.root, path.stem)
            for path in sorted((self.root / "release-products").glob("*.toml"))
        ]

    def _manifests(self) -> list[ProductManifest]:
        """The formula manifests: the rules below are formula rules."""
        return [p for p in self._products() if isinstance(p, ProductManifest)]

    def test_every_formula_has_a_manifest(self) -> None:
        formulae = {p.stem for p in (self.root / "Formula").glob("*.rb")}
        manifests = {m.formula for m in self._manifests()}
        self.assertEqual(
            formulae - manifests,
            set(),
            "a shipped formula with no manifest cannot be released by the engine",
        )

    def test_no_two_manifests_compose_the_same_tag(self) -> None:
        version = "0.1.9"
        tags = [m.tag(version) for m in self._manifests()]
        self.assertEqual(
            len(tags), len(set(tags)), f"tag collision across products: {tags}"
        )

    def test_manifest_repository_matches_formula_source_url(self) -> None:
        """The top-level `url` stanza, not the bottle root_url, which already
        points at the tap and would mask a mismatch."""
        source_url = re.compile(r'^ {2}url "([^"]+)"', re.MULTILINE)
        for manifest in self._manifests():
            with self.subTest(product=manifest.name):
                content = (self.root / f"Formula/{manifest.formula}.rb").read_text()
                match = source_url.search(content)
                assert match is not None, f"no source url in {manifest.formula}.rb"
                self.assertIn(
                    f"github.com/{manifest.repository}/",
                    match.group(1),
                    "formula source url names a repository the manifest does not",
                )

    def test_every_manifest_composes_a_tag_the_repository_publishes(self) -> None:
        """Published tags are `<name>-<version>`, so a `v` in the prefix composes
        a tag that resolves to nothing. Shape only: reaching the network to
        confirm a tag exists belongs in CI, not in the unit suite."""
        for manifest in self._manifests():
            with self.subTest(product=manifest.name):
                self.assertEqual(
                    manifest.tag("0.1.9"),
                    f"{manifest.name}-0.1.9",
                    "manifest composes a tag the repository does not publish",
                )

    def test_the_release_engine_can_rewrite_every_formula_url(self) -> None:
        """Every shipped formula exposes a replaceable GitHub source URL.

        Repository ownership is asserted separately by
        `test_manifest_repository_matches_formula_source_url`; this check
        ensures the updater can perform the release cutover first.
        """
        from modules.engine.application.tap import source_url_pattern

        for manifest in self._manifests():
            with self.subTest(product=manifest.name):
                content = (self.root / f"Formula/{manifest.formula}.rb").read_text()
                self.assertRegex(content, source_url_pattern())

    def test_macos_only_matches_the_formula(self) -> None:
        for manifest in self._manifests():
            with self.subTest(product=manifest.name):
                content = (self.root / f"Formula/{manifest.formula}.rb").read_text()
                self.assertEqual(
                    manifest.macos_only,
                    "depends_on :macos" in content,
                    "manifest macos_only disagrees with the formula",
                )

    def test_a_formula_ships_on_the_python_its_bottle_was_built_on(self) -> None:
        """A bottle's venv points at the Python it was built with. Changing a
        formula's Python without rebuilding its bottle pours a venv whose
        Python is no longer a dependency, as sive's did on main once."""
        python = re.compile(r'depends_on "python@(3\.\d+)"')
        for manifest in self._manifests():
            path = f"Formula/{manifest.formula}.rb"
            with self.subTest(product=manifest.name):
                current = (self.root / path).read_text()
                if "bottle do" not in current:
                    continue
                bottle_commit = self._git(
                    "log", "-1", "--format=%H", "-G", "sha256 cellar:", "--", path
                )
                if not bottle_commit:
                    self.skipTest("history unavailable (shallow clone)")
                built_on = python.search(self._git("show", f"{bottle_commit}:{path}"))
                ships_on = python.search(current)
                assert built_on and ships_on, f"{path} names no python@"
                self.assertEqual(
                    ships_on.group(1),
                    built_on.group(1),
                    f"{path} ships on python@{ships_on.group(1)} but its bottle was "
                    f"built on python@{built_on.group(1)} at {bottle_commit[:7]}; "
                    "change the Python in a formula PR that rebuilds the bottle",
                )

    def _git(self, *args: str) -> str:
        git = shutil.which("git")
        assert git, "git is required to read a formula's bottle history"
        return subprocess.run(
            [git, *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def test_every_formula_builds_on_the_tap_python(self) -> None:
        """The tap ships on the Python it tests on, `.python-version`. A formula
        that depends on a homebrew-core Python library must build its venv on a
        Python that library was built for: `cryptography` built for 3.14 is
        invisible to a 3.13 venv, and only the formula test sees it."""
        tap_python = (self.root / TAP_PYTHON_FILE).read_text().strip()
        for manifest in self._manifests():
            expected = PYTHON_MIGRATION_PENDING.get(manifest.formula, tap_python)
            with self.subTest(product=manifest.name, python=expected):
                content = (self.root / f"Formula/{manifest.formula}.rb").read_text()
                self.assertIn(
                    f'depends_on "python@{expected}"',
                    content,
                    f"formula must depend on python@{expected}; a migrated formula "
                    "leaves PYTHON_MIGRATION_PENDING",
                )
                self.assertIn(
                    f'virtualenv_create(libexec, "python{expected}")',
                    content,
                    f"formula must build its venv on python{expected}",
                )

    def test_no_formula_installs_on_intel_macos(self) -> None:
        """Intel macOS is Homebrew support tier 3 and gets no new bottles. A
        macOS-only formula limits itself with a plain `depends_on arch:`; one
        that also runs on Linux limits only its macOS side, so Linux stays."""
        plain = "  depends_on arch: :arm64\n"
        macos_side = "  on_macos do\n    depends_on arch: :arm64\n  end\n"
        for manifest in self._manifests():
            with self.subTest(product=manifest.name):
                content = (self.root / f"Formula/{manifest.formula}.rb").read_text()
                self.assertIn(
                    plain if manifest.macos_only else macos_side,
                    content,
                    "formula does not exclude Intel macOS",
                )

    def test_no_product_declares_intel_macos_support(self) -> None:
        """A product's own platform constraint narrows the supported set and
        never widens it: no formula or cask may declare Intel support, whatever
        arm64 limit it also carries. Held for the cask like any formula."""
        sources = {
            product.name: (
                self.root
                / (
                    product.path
                    if isinstance(product, CaskManifest)
                    else f"Formula/{product.formula}.rb"
                )
            ).read_text()
            for product in self._products()
        }
        for name, source in sources.items():
            with self.subTest(product=name):
                self.assertEqual(
                    intel_declarations(source), [], "product declares Intel support"
                )

    def test_intel_declarations_names_every_form_homebrew_offers(self) -> None:
        cases = {
            "depends_on arch: :x86_64\n": ["depends_on arch: :x86_64"],
            "depends_on arch: :intel\n": ["depends_on arch: :intel"],
            "depends_on arch: [:x86_64]\n": ["depends_on arch: [:x86_64]"],
            "depends_on arch: [:arm64, :intel]\n": [
                "depends_on arch: [:arm64, :intel]"
            ],
            "depends_on arch: [:arm64]\n": [],
            "  on_intel do\n    depends_on 'x'\n  end\n": ["on_intel"],
            "if Hardware::CPU.intel?\n  x\nend\n": ["Hardware::CPU.intel?"],
            "depends_on arch: :arm64\n": [],
            "on_macos do\n  depends_on arch: :arm64\nend\n": [],
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(intel_declarations(source), expected)

    def test_no_formula_hand_authors_its_bottle_block(self) -> None:
        """The bottle block is output, not source. `update_formula` deletes it
        on every release (`_BOTTLE_BLOCK.sub`) and `brew pr-pull` regenerates
        it from Homebrew's own template (`dev-cmd/bottle.rb:27-33`), which
        emits `root_url` only when it differs from the default domain.

        So each `root_url` is per-formula and per-version, derived from the
        tag, and nothing about it is shared or hand-maintained. Anything
        clever here — a parse-time global reading JSON, as `aws-tap` does, or
        an interpolated constant — is overwritten by the next `pr-pull`, and
        pins obsolete symbols in the meantime. Each line must be a literal.
        """
        for manifest in self._manifests():
            with self.subTest(product=manifest.name):
                content = (self.root / f"Formula/{manifest.formula}.rb").read_text()
                block = re.search(
                    r"^ {2}bottle do\n(.*?)^ {2}end$", content, re.DOTALL | re.MULTILINE
                )
                if block is None:
                    continue  # between releases the engine leaves none
                for line in block.group(1).splitlines():
                    if "root_url" not in line:
                        continue
                    self.assertRegex(
                        line.strip(),
                        r'^root_url "https://github\.com/\S+"$',
                        f"{manifest.formula}: root_url must be the literal "
                        "pr-pull writes, not an interpolation or a lookup",
                    )

    def test_every_cask_has_a_manifest_of_its_own_kind(self) -> None:
        """A cask used to carry no manifest, so no check could see it. It has one
        now, of kind `cask`, and is held to the cask rules; the formula rules in
        this class iterate formula manifests only.

        They would be wrong for it. `macos_only` is checked against
        `depends_on :macos`, a formula spelling: a cask is macOS-only by
        definition, and its DSL takes `depends_on macos:` only as a version
        constraint (`cask/dsl/depends_on.rb:110`), never the bare symbol.
        """
        casks = [p for p in self._products() if isinstance(p, CaskManifest)]
        self.assertEqual(
            {p.stem for p in (self.root / "Casks").glob("*.rb")},
            {cask.cask for cask in casks},
            "a shipped cask with no manifest cannot be checked before it is committed",
        )
        self.assertEqual(
            {cask.name for cask in casks} & {m.name for m in self._manifests()},
            set(),
            "a cask must not be pulled into the formula rules",
        )

    def test_every_formula_declares_a_prefix_anchored_livecheck(self) -> None:
        r"""A version bump must be discoverable rather than remembered.

        `strategy :github_latest` is the corpus default (591 uses to 51), but
        it asks GitHub for a repository's single latest release. All three
        products release into this one tap under `<product>-` tag prefixes, so
        it would answer with whichever product released most recently. This
        tap needs `:github_releases`, which applies a regex to every tag.

        Its `DEFAULT_REGEX` is `/v?(\d+(?:\.\d+)+)/i` — unanchored, so it
        matches `0.1.8` in `sive-0.1.8` no matter which product owns the tag,
        and the three formulae would track each other. Require each to name a
        regex anchored to its own manifest prefix.
        """
        for manifest in self._manifests():
            with self.subTest(product=manifest.name):
                content = (self.root / f"Formula/{manifest.formula}.rb").read_text()
                block = _LIVECHECK_BLOCK.search(content)
                if block is None:
                    self.fail(f"{manifest.formula} declares no livecheck block")
                body = block.group(1)
                self.assertIn("url :stable", body)
                self.assertIn(
                    "strategy :github_releases",
                    body,
                    f"{manifest.formula}: :github_latest cannot tell this tap's "
                    "products apart",
                )
                self.assertRegex(
                    body,
                    rf"regex\(/\^{re.escape(manifest.tag_prefix)}",
                    f"{manifest.formula}: the regex must anchor on "
                    f"{manifest.tag_prefix!r}, or it matches a sibling's tag",
                )


if __name__ == "__main__":
    unittest.main()
