"""The WebOS client key is stored by bscpylgtv in a pickled SQLite value.

pickle.loads executes whatever the payload says, so a writable keyfile would
be arbitrary code execution. The stored value is only ever a string, so a
restricted unpickler is enough without abandoning upstream's format.
"""

from __future__ import annotations

import pickle
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lgtvctrl.config import Config

KEY = "192.168.1.50"


def _keyfile(tmp_path: Path, payload: bytes) -> str:
    path = tmp_path / "keys.sqlite"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE unnamed (key TEXT, value BLOB)")
        con.execute("INSERT INTO unnamed VALUES (?, ?)", (KEY, payload))
    return str(path)


def test_reads_a_stored_string_key(tmp_path: Path) -> None:
    path = _keyfile(tmp_path, pickle.dumps("a" * 32))
    assert Config.extract_client_key(path, KEY) == "a" * 32


def test_refuses_a_payload_that_would_execute_code(tmp_path: Path) -> None:
    """A pickle naming a callable must not be unpickled."""

    class Exploit:
        def __reduce__(self) -> tuple[object, tuple[str, ...]]:
            return (print, ("pwned",))

    path = _keyfile(tmp_path, pickle.dumps(Exploit()))
    assert Config.extract_client_key(path, KEY) is None


def test_missing_key_returns_none(tmp_path: Path) -> None:
    path = _keyfile(tmp_path, pickle.dumps("x" * 32))
    assert Config.extract_client_key(path, "10.0.0.1") is None
