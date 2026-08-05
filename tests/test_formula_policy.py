from __future__ import annotations

import unittest
from pathlib import Path


class FormulaPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_sive_uses_homebrew_python_application_conventions(self) -> None:
        content = (self.root / "Formula/sive.rb").read_text()
        self.assertIn("include Language::Python::Virtualenv", content)
        self.assertIn('depends_on "python@3.13"', content)
        self.assertIn("virtualenv_install_with_resources", content)
        self.assertIn(
            'assert_match version.to_s, shell_output("#{bin}/sive --version")', content
        )
        self.assertNotIn('depends_on "uv"', content)
        self.assertNotIn("pip --prefix", content)


if __name__ == "__main__":
    unittest.main()
