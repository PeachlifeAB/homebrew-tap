from __future__ import annotations

# ETA: ~93s observed 2026-04-02
import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from sive.core.bw import (
    delete_folder,
    delete_item,
    find_folder_id,
    list_folders,
    list_items_in_folder,
    unlock,
)
from sive.core.keychain_macos import get_password
from sive.core.vaults import load_vault

BASE_DIR = Path("/private/tmp/sive/tdd/testx")


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def _mise_env(cwd: Path) -> dict[str, str]:
    result = _run(["mise", "env", "-C", str(cwd), "-J"], cwd)
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def _purge_tag(tag: str, session_key: str, appdata_dir: str) -> None:
    """Delete a smoke-test tag folder and everything in it."""
    folders = list_folders(session_key, appdata_dir=appdata_dir)
    folder_id = find_folder_id(folders, f"env/{tag}")
    if not folder_id:
        return
    for item in list_items_in_folder(folder_id, session_key, appdata_dir=appdata_dir):
        item_id = item.get("id")
        if item_id:
            delete_item(item_id, session_key, appdata_dir=appdata_dir)
    delete_folder(folder_id, session_key, appdata_dir=appdata_dir)


def _purge_tags(tags: tuple[str, ...]) -> None:
    """Best effort teardown: leaving folders behind would poison a rerun."""
    vault = load_vault("personal")
    appdata_dir = str(vault.appdata_dir)
    try:
        session_key = unlock(get_password("personal"), appdata_dir=appdata_dir)
    except Exception:  # noqa: BLE001
        return
    if not session_key:
        return
    for tag in tags:
        _purge_tag(tag, session_key, appdata_dir)


@pytest.fixture
def sive_executable() -> str:
    """The installed sive, or skip: this suite exercises a real vault."""
    if os.getenv("SIVE_RUN_LIVE_SMOKE") != "1":
        pytest.skip("set SIVE_RUN_LIVE_SMOKE=1 to run live smoke test")
    sive = shutil.which("sive")
    if not sive:
        pytest.skip("installed sive executable not found")
    return sive


@pytest.fixture
def project_dirs() -> Iterator[tuple[Path, Path, str, str]]:
    """Two clean project directories with unique tags, purged afterwards."""
    shutil.rmtree(BASE_DIR, ignore_errors=True)
    dir_a = BASE_DIR / "parent-a"
    dir_b = BASE_DIR / "parent-b"
    dir_a.mkdir(parents=True, exist_ok=True)
    dir_b.mkdir(parents=True, exist_ok=True)

    suffix = str(int(time.time()))
    tag_a = f"test_smoke_a_{suffix}"
    tag_b = f"test_smoke_b_{suffix}"
    try:
        yield dir_a, dir_b, tag_a, tag_b
    finally:
        _purge_tags((tag_a, tag_b))


def _setup_project(sive: str, cwd: Path, tag: str) -> None:
    result = _run([sive, "setup", "--tag", tag, "--no-global"], cwd)
    assert result.returncode == 0, result.stderr or result.stdout


def _assert_project_marker(directory: Path) -> None:
    """`sive setup` writes .sive and must not create a mise config."""
    assert (directory / ".sive").exists()
    assert (directory / ".sive").read_text().strip()
    assert not (directory / "mise.toml").exists()
    assert not (directory / ".mise.toml").exists()


def test_two_project_dirs_are_isolated_with_dot_sive(
    sive_executable: str, project_dirs: tuple[Path, Path, str, str]
) -> None:
    """A key set in one project must not leak into another."""
    dir_a, dir_b, tag_a, tag_b = project_dirs
    shared_key = "SIVE_SMOKE_SHARED"
    a_only = "SIVE_SMOKE_A_ONLY"
    b_only = "SIVE_SMOKE_B_ONLY"
    val_a = f"A_{tag_a}"
    val_b = f"B_{tag_b}"

    for cwd, tag in ((dir_a, tag_a), (dir_b, tag_b)):
        _setup_project(sive_executable, cwd, tag)
    _assert_project_marker(dir_a)
    _assert_project_marker(dir_b)

    writes = (
        (dir_a, shared_key, val_a),
        (dir_a, a_only, val_a),
        (dir_b, shared_key, val_b),
        (dir_b, b_only, val_b),
    )
    for cwd, key, value in writes:
        result = _run([sive_executable, "set", key, value], cwd)
        assert result.returncode == 0, result.stderr or result.stdout

    env_a = _mise_env(dir_a)
    env_b = _mise_env(dir_b)

    assert env_a[shared_key] == val_a
    assert env_a[a_only] == val_a
    assert b_only not in env_a, "b's key leaked into a"

    assert env_b[shared_key] == val_b
    assert env_b[b_only] == val_b
    assert a_only not in env_b, "a's key leaked into b"
