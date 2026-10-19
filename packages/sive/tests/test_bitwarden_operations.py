from __future__ import annotations

import base64
import json
import subprocess

import pytest

from sive.core import bw


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("malformed", [False, True])
def test_note_upsert_preserves_payload(
    monkeypatch, authentication, tmp_path, existing, malformed
):
    fixture = authentication
    item = {"id": fixture.vault_name, "name": fixture.email, "type": 2}
    items = [dict(item, type=1), dict(item, name=fixture.server)]
    if existing:
        items.append(item)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        output = fixture.server if malformed else json.dumps(items)
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(subprocess, "run", run)
    bw.upsert_note(
        fixture.email,
        fixture.password,
        fixture.vault_name,
        fixture.session,
        appdata_dir=tmp_path,
    )
    command = calls[-1]
    editing = existing and not malformed
    assert command[2:4] == (["edit", "item"] if editing else ["create", "item"])
    payload = json.loads(base64.b64decode(command[5 if editing else 4]))
    assert payload["notes"] == fixture.password
    assert payload["name"] == fixture.email
    if editing:
        assert command[4] == fixture.vault_name
    else:
        assert payload["folderId"] == fixture.vault_name


@pytest.mark.parametrize("status_failure", [False, True])
@pytest.mark.parametrize("matching", [False, True])
def test_server_configuration_skips_matching_server(
    monkeypatch, authentication, tmp_path, status_failure, matching
):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[2] == "status":
            output = json.dumps(
                {"serverUrl": authentication.server + "/" if matching else ""}
            )
            return subprocess.CompletedProcess(
                args, int(status_failure), output, authentication.network_failure
            )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    changed = bw.set_server(authentication.server, appdata_dir=tmp_path)
    assert changed is (status_failure or not matching)
    assert len(calls) == (2 if changed else 1)
    assert (
        bw.set_server(
            authentication.server,
            status={"serverUrl": authentication.server},
            appdata_dir=tmp_path,
        )
        is False
    )


@pytest.mark.parametrize("malformed", [False, True])
def test_folder_and_item_responses(monkeypatch, authentication, tmp_path, malformed):
    folder = {
        "id": authentication.vault_name,
        "name": "env/" + authentication.vault_name,
    }
    folders = [
        folder,
        {"name": "env/"},
        {"name": "env/invalid tag"},
        {"name": authentication.email},
    ]

    def run(args, **kwargs):
        if malformed:
            output = authentication.server
        elif args[2] == "create":
            output = json.dumps(folder)
        else:
            output = json.dumps(folders)
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(subprocess, "run", run)
    assert bw.list_env_tags(authentication.session, appdata_dir=tmp_path) == (
        [] if malformed else [authentication.vault_name]
    )
    assert bw.list_items_in_folder(
        authentication.vault_name, authentication.session, appdata_dir=tmp_path
    ) == ([] if malformed else folders)
    assert bw.find_folder_id(folders, folder["name"]) == authentication.vault_name
    assert bw.find_folder_id(folders, authentication.server) is None
    if malformed:
        with pytest.raises(bw.BWError, match="Failed to parse"):
            bw.create_folder(
                authentication.vault_name, authentication.session, appdata_dir=tmp_path
            )
    else:
        assert (
            bw.create_folder(
                authentication.vault_name, authentication.session, appdata_dir=tmp_path
            )
            == authentication.vault_name
        )
    bw.delete_item(
        authentication.vault_name, authentication.session, appdata_dir=tmp_path
    )
    bw.delete_folder(
        authentication.vault_name, authentication.session, appdata_dir=tmp_path
    )


def test_extract_environment_ignores_non_notes_and_invalid_names(authentication):
    name = authentication.vault_name.upper().replace("-", "_")
    items = [
        {"type": 1, "name": name, "notes": authentication.password},
        {"type": 2, "name": authentication.email, "notes": authentication.password},
        {"type": 2, "name": name, "notes": authentication.password},
        {"type": 2, "name": name + "_EMPTY", "notes": None},
    ]
    assert bw.extract_env_vars(items) == {
        name: authentication.password,
        name + "_EMPTY": "",
    }
