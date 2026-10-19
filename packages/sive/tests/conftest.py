from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


@dataclass(frozen=True)
class AuthenticationFixture:
    vault_name: str
    email: str
    password: str
    session: str
    server: str
    rejected_grant: str
    missing_login: str
    wrong_password: str
    network_failure: str
    additional_factor: str


@pytest.fixture
def authentication() -> AuthenticationFixture:
    directory = Path(__file__).parent / "fixtures"
    values = json.loads((directory / "vault_authentication.json").read_text())
    schema = json.loads((directory / "vault_authentication.schema.json").read_text())
    Draft202012Validator(schema).validate(values)
    return AuthenticationFixture(**values)
