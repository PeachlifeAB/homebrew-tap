"""`.dog/sense.json` is gitignored, so nothing else would catch it drifting
from the schema it declares. The schema is fetched from the URL the file
itself names, rather than a copy that can go stale.
"""

from __future__ import annotations

import json
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENSE = ROOT / ".dog" / "sense.json"


class SenseSchemaTests(unittest.TestCase):
    def test_sense_matches_the_schema_it_declares(self) -> None:
        if not SENSE.exists():
            self.skipTest("no .dog/sense.json in this checkout")

        jsonschema = __import__("jsonschema")
        sense = json.loads(SENSE.read_text(encoding="utf-8"))

        # The URL comes from the file under test, so the scheme is checked
        # rather than trusted: a file:// $schema would otherwise be read.
        url = sense["$schema"]
        self.assertTrue(
            url.startswith("https://"), f"$schema must be https, got {url!r}"
        )

        # The host rejects a request with no User-Agent.
        request = urllib.request.Request(
            url, headers={"User-Agent": "homebrew-tap-tests"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                schema = json.load(response)
        except (urllib.error.URLError, TimeoutError) as error:
            self.skipTest(f"schema unreachable: {error}")

        errors = sorted(
            jsonschema.Draft202012Validator(schema).iter_errors(sense),
            key=lambda error: list(error.path),
        )
        self.assertEqual(
            [],
            [f"{list(e.path)}: {e.message}" for e in errors],
        )


if __name__ == "__main__":
    unittest.main()
