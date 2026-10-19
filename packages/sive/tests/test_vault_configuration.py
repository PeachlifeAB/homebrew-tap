from __future__ import annotations

from pathlib import Path

import pytest

from sive.core import vaults


@pytest.fixture
def isolated_configuration(monkeypatch, tmp_path):
    configuration = tmp_path / "config"
    monkeypatch.setattr(vaults, "CONFIG_DIR", configuration)
    monkeypatch.setattr(vaults, "VAULTS_TOML", configuration / "vaults.toml")
    monkeypatch.setattr(vaults, "DATA_DIR", tmp_path / "data")
    return configuration / "vaults.toml"


def test_missing_configuration_explains_setup(isolated_configuration):
    with pytest.raises(vaults.ConfigError, match="Run 'sive setup'"):
        vaults.load_vault()


def test_vault_round_trip_preserves_other_vaults(
    isolated_configuration, authentication
):
    vaults.write_vault_stub(authentication.vault_name, authentication.server)
    first = vaults.load_vault(authentication.vault_name)
    assert first.server == authentication.server
    assert first.appdata_dir == vaults.DATA_DIR / "vaults" / authentication.vault_name

    vaults.write_vault_stub(
        authentication.vault_name + "_secondary", authentication.server
    )
    assert vaults.load_vault(authentication.vault_name) == first
    assert (
        vaults.load_vault(authentication.vault_name + "_secondary").server
        == authentication.server
    )


def test_vault_update_preserves_custom_directory(
    isolated_configuration, authentication
):
    vaults.write_vault_stub(authentication.vault_name, authentication.server)
    with isolated_configuration.open("a") as configuration:
        configuration.write(f'appdata_dir = "{isolated_configuration.parent}"\n')
    vaults.write_vault_stub(authentication.vault_name, authentication.server)
    assert vaults.load_vault(authentication.vault_name).appdata_dir == Path(
        isolated_configuration.parent
    )


def test_unknown_vault_explains_setup(isolated_configuration, authentication):
    vaults.write_vault_stub(authentication.vault_name, authentication.server)
    with pytest.raises(vaults.ConfigError, match="not found"):
        vaults.load_vault(authentication.email)


def test_empty_server_explains_required_url(isolated_configuration, authentication):
    vaults.write_vault_stub(authentication.vault_name, "")
    with pytest.raises(vaults.ConfigError, match="missing a 'server'"):
        vaults.load_vault(authentication.vault_name)


def test_invalid_toml_reports_configuration_error(isolated_configuration):
    isolated_configuration.parent.mkdir()
    isolated_configuration.write_text("[vaults\n")
    with pytest.raises(vaults.ConfigError, match="Invalid TOML"):
        vaults.load_vault()
