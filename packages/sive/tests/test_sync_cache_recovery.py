from __future__ import annotations

import pytest

from sive.core import sync_state


@pytest.mark.parametrize("invalid_json", [False, True])
def test_unusable_tag_cache_is_ignored(
    monkeypatch, tmp_path, authentication, invalid_json
):
    monkeypatch.setattr(sync_state, "STATE_DIR", tmp_path)
    path = sync_state.state_path(authentication.vault_name)
    if invalid_json:
        path.write_text("{")
    else:
        sync_state.save_sync_state(
            authentication.vault_name, {"known_tags": authentication.email}
        )
    assert sync_state.load_known_tags(authentication.vault_name) == []


def test_invalid_sync_timestamp_requests_sync(monkeypatch, tmp_path, authentication):
    monkeypatch.setattr(sync_state, "STATE_DIR", tmp_path)
    sync_state.save_sync_state(
        authentication.vault_name, {"last_successful_sync_at": authentication.email}
    )
    assert sync_state.is_sync_due(authentication.vault_name)


def test_recent_sync_does_not_launch_background_process(
    monkeypatch, tmp_path, authentication
):
    monkeypatch.setattr(sync_state, "STATE_DIR", tmp_path)
    sync_state.save_sync_state(
        authentication.vault_name,
        {"last_successful_sync_at": sync_state.to_timestamp(sync_state.utc_now())},
    )
    assert sync_state.maybe_trigger_background_sync(authentication.vault_name) is False
    assert not sync_state.lock_path(authentication.vault_name).exists()
