import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "src" / "sive" / "mise_hook" / "env.sh"
REENTRY_CAP = 5


def _fake_sive_as_mise_shim(bin_dir: Path, calls: Path) -> None:
    """A `sive` that behaves like a mise shim: it re-runs hook-env, which
    sources the hook again, before printing the real exports."""
    fake = bin_dir / "sive"
    fake.write_text(
        "#!/bin/bash\n"
        f'echo call >> "{calls}"\n'
        f'[ "$(wc -l < "{calls}")" -gt {REENTRY_CAP} ] && exit 1\n'
        "/bin/bash -c '. \"$SIVE_HOOK\"; export -p' >/dev/null\n"
        "echo \"export SIVE_TEST_SECRET='ok'\"\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)


def _source_hook_like_mise(bin_dir: Path) -> str:
    """mise sources `_.source` scripts in bash and keeps what they export."""
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "SIVE_HOOK": str(HOOK)}
    result = subprocess.run(
        ["/bin/bash", "-c", '. "$SIVE_HOOK"; export -p'],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout


def test_mise_hook_does_not_reenter_when_sive_is_a_mise_shim(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    _fake_sive_as_mise_shim(bin_dir, calls)

    exported = _source_hook_like_mise(bin_dir)

    assert calls.read_text(encoding="utf-8").count("call") == 1
    assert "SIVE_TEST_SECRET" in exported


def test_mise_hook_reentry_guard_is_not_exported(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_sive_as_mise_shim(bin_dir, tmp_path / "calls")

    exported = _source_hook_like_mise(bin_dir)

    assert "SIVE_MISE_HOOK_ACTIVE" not in exported
