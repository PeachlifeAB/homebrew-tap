from argparse import Namespace
from unittest.mock import Mock

from modules.engine.api.cli import _resume


def test_resume_verifies_an_already_published_release_without_republishing() -> None:
    context = Mock()
    observation = context.producer.observe.return_value
    observation.remote_tag_commit = "released-commit"
    observation.github_release_exists = True
    context.tap.is_published.return_value = True

    _resume(Namespace(version="0.1.13"), context)

    context.tap.is_published.assert_called_once_with("0.1.13")
    context.tap.post_verify.assert_called_once_with("0.1.13")
    context.tap.create_formula_pull_request.assert_not_called()
    context.tap.wait_and_publish.assert_not_called()
    context.process.read_bytes.assert_not_called()


def test_publication_detection_reads_remote_main_and_matches_exact_asset() -> None:
    from pathlib import Path

    from modules.engine.application.tap import TapRelease
    from modules.engine.infrastructure.manifest import load_manifest

    root = Path(__file__).resolve().parents[1]
    manifest = load_manifest(root, "sive")
    git = Mock()
    tap = TapRelease(root, manifest, Mock(), git, Mock())
    for published_version in ("0.1.12", "0.1.13", "0.1.130"):
        git.output.return_value = f'  url "{manifest.asset_url(published_version)}"\n'
        assert tap.is_published("0.1.13") is (published_version == "0.1.13")
        git.output.assert_called_with(["show", "origin/main:Formula/sive.rb"], cwd=root)
    assert git.run.call_count == 3
