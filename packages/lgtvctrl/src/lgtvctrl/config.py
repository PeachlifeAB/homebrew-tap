"""Config + paths for lgtvctrl. No network dependencies."""

from __future__ import annotations

import io
import json
import os
import pickle
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
XDG_STATE_HOME = Path(
    os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
)

CONFIG_DIR = XDG_CONFIG_HOME / "lgtvctrl"
CONFIG_FILE = CONFIG_DIR / "config.json"
KEYFILE_PATH = CONFIG_DIR / ".aiopylgtv.sqlite"

STATE_DIR = XDG_STATE_HOME / "lgtvctrl"
IDENTIFIERS_CACHE_FILE = STATE_DIR / "identifiers.json"


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


class _UnpickleError(Exception):
    """A stored value tried to name a callable."""


class _DataOnlyUnpickler(pickle.Unpickler):
    """Unpickler that refuses to resolve any global.

    ``find_class`` is the hook every code-executing pickle must pass through:
    GLOBAL and STACK_GLOBAL resolve a name here before REDUCE can call it.
    Refusing outright leaves only the plain-data opcodes.
    """

    def find_class(self, module: str, name: str) -> object:
        raise _UnpickleError(f"refused to resolve {module}.{name}")


def _loads_data_only(payload: bytes) -> str | None:
    """Unpickle a value that must be a plain string, or return None."""
    try:
        value = _DataOnlyUnpickler(io.BytesIO(payload)).load()
    except (_UnpickleError, pickle.UnpicklingError, EOFError, AttributeError):
        return None
    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class TVConfig:
    ip: str
    pc_input: str | None = None
    mac: str | None = None
    uuid: str | None = None

    @classmethod
    def load(cls) -> TVConfig:
        if not CONFIG_FILE.exists():
            raise FileNotFoundError(f"Missing {CONFIG_FILE}. Run 'tv auth'.")

        data = read_json(CONFIG_FILE)
        ip = data.get("ip")
        if not isinstance(ip, str) or not ip:
            raise ValueError(f"Invalid config: missing 'ip' in {CONFIG_FILE}")

        pc_input = data.get("pc_input")
        mac = data.get("mac")
        uuid = data.get("uuid")

        return cls(
            ip=ip,
            pc_input=pc_input if isinstance(pc_input, str) else None,
            mac=mac if isinstance(mac, str) else None,
            uuid=uuid if isinstance(uuid, str) else None,
        )

    def save(self) -> None:
        data = read_json(CONFIG_FILE)
        data["ip"] = self.ip
        if self.pc_input is not None:
            data["pc_input"] = self.pc_input
        if self.mac is not None:
            data["mac"] = self.mac
        if self.uuid is not None:
            data["uuid"] = self.uuid
        _write_json(CONFIG_FILE, data)


class Config:
    TIMEOUT = 5

    _tv_config: TVConfig | None = None

    @classmethod
    def get_tv_config(cls) -> TVConfig:
        if cls._tv_config is None:
            cls._tv_config = TVConfig.load()
        return cls._tv_config

    @classmethod
    def clear_cache(cls) -> None:
        cls._tv_config = None

    @staticmethod
    def extract_client_key(keyfile_path: str, tv_ip: str) -> str | None:
        """Read the WebOS client key bscpylgtv stored for this TV.

        bscpylgtv writes the keystore with sqlitedict, which pickles its
        values, so the format is upstream's and cannot simply be changed. The
        stored value is only ever the key string, so unpickling is restricted
        to plain data: a payload naming any callable is refused rather than
        executed.
        """
        try:
            with sqlite3.connect(keyfile_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT value FROM unnamed WHERE key = ?", (tv_ip,))
                row = cur.fetchone()
                return _loads_data_only(row[0]) if row else None
        except (sqlite3.Error, OSError, _UnpickleError):
            return None
