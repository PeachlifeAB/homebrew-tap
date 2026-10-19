from __future__ import annotations

import pytest

from sive.commands import set_secret
from sive.core.vaults import ConfigError


def test_write_requires_value_before_accessing_configuration(
    monkeypatch, authentication, capsys
):
    def unexpected(*args, **kwargs):
        pytest.fail("Missing value must fail before accessing vault configuration")

    monkeypatch.setattr(set_secret, "load_vault", unexpected)
    assert set_secret.run(authentication.vault_name) == 1
    assert "a value is required" in capsys.readouterr().err


def test_write_reports_invalid_vault_configuration(monkeypatch, authentication, capsys):
    def invalid(*args, **kwargs):
        raise ConfigError(authentication.network_failure)

    monkeypatch.setattr(set_secret, "load_vault", invalid)
    assert (
        set_secret.run(
            authentication.vault_name,
            authentication.password,
            tag=authentication.vault_name,
        )
        == 1
    )
    assert authentication.network_failure in capsys.readouterr().err
