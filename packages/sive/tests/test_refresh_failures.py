from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sive.commands import refresh
from sive.core import vaults
from sive.core.credentials import CredentialError
from sive.core.source_loader import SourceError


@pytest.mark.parametrize(
    "failure", ["invalid", "key", "source", "unexpected", "snapshot"]
)
def test_refresh_reports_failures_without_aborting_later_tags(
    monkeypatch, authentication, tmp_path, capsys, failure
):
    vault = vaults.VaultConfig(
        authentication.vault_name, authentication.server, tmp_path
    )
    monkeypatch.setattr(vaults, "load_vault", lambda name: vault)
    monkeypatch.setattr(refresh, "sync", lambda *args, **kwargs: None)
    processed = []

    def ensure_key(vault_name, tag):
        if tag == "failed" and failure == "key":
            raise CredentialError(authentication.network_failure)

    def load_source(source, **kwargs):
        error_type = {"source": SourceError, "unexpected": OSError}.get(failure)
        if source.endswith("/failed") and error_type:
            raise error_type(authentication.network_failure)
        return {"SECRET": authentication.password}

    def write_snapshot(vault_name, tag, env, sources):
        from sive.core.snapshot import SnapshotMeta

        if tag == "failed" and failure == "snapshot":
            raise OSError(authentication.network_failure)
        processed.append(tag)
        return SnapshotMeta(
            vault=vault_name,
            tag=tag,
            sources=sources,
            item_count=len(env),
            updated_at=datetime.now(UTC),
            refresh_ok=True,
        )

    monkeypatch.setattr(refresh, "ensure_key", ensure_key)
    monkeypatch.setattr(refresh, "load_source", load_source)
    monkeypatch.setattr(refresh, "write_snapshot", write_snapshot)
    failed_source = (
        "" if failure == "invalid" else authentication.vault_name + ".folder:env/failed"
    )
    healthy_source = authentication.vault_name + ".folder:env/healthy"
    assert (
        refresh.run(
            authentication.vault_name,
            [failed_source, healthy_source],
            session_key=authentication.session,
        )
        == 1
    )
    assert processed == ["healthy"]
    captured = capsys.readouterr()
    assert "sive:" in captured.err
    assert "[healthy] 1 vars written" in captured.out
