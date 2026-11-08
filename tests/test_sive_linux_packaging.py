import re
import tomllib
from pathlib import Path


def test_sive_formula_vendors_linux_credential_dependencies() -> None:
    root = Path(__file__).resolve().parents[1]
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    packages = {package["name"]: package for package in lock["package"]}
    formula = (root / "Formula/sive.rb").read_text(encoding="utf-8")
    resources = {
        name.replace(".", "-").lower()
        for name in re.findall(r'resource "([^"]+)" do', formula)
    }
    system_dependencies = set(re.findall(r'depends_on "([^"]+)"', formula))
    pending = ["keyring"]
    required: set[str] = set()
    while pending:
        name = pending.pop()
        if name in required or name in system_dependencies:
            continue
        required.add(name)
        pending.extend(
            dependency["name"] for dependency in packages[name].get("dependencies", [])
        )
    assert required <= resources, (
        f"Missing Linux credential resources: {sorted(required - resources)}"
    )
