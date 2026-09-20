from __future__ import annotations

from pathlib import Path

from bgtail.cli import _log_dir, main


class PopenSpy:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))

        class Proc:
            pid = 12345

            def wait(self) -> int:
                return 0

        return Proc()


def test_global_log_lives_under_state_home(monkeypatch, tmp_path: Path) -> None:
    """Global logs are per-caller-directory but under XDG_STATE_HOME, not /tmp,
    which is world-writable with a predictable name."""
    monkeypatch.chdir(tmp_path)
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))

    assert _log_dir("global") == state / "bgtail" / tmp_path.name


def test_passthrough_forwards_project_log_flag(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NO_WINDOW", "1")

    from bgtail import cli

    spy = PopenSpy()
    monkeypatch.setattr(cli.subprocess, "Popen", spy)
    monkeypatch.setattr(cli, "_wait_for_exit_file", lambda job_id, log_mode: 0)

    rc = main(["--project-log", "echo", "hello"])
    assert rc == 0

    runner_argv = spy.calls[0]
    assert "--project-log" in runner_argv

    sep = runner_argv.index("--")
    forwarded = runner_argv[sep + 1 :]
    assert forwarded == ["echo", "hello"]


def test_passthrough_forwards_global_log_flag(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NO_WINDOW", "1")

    from bgtail import cli

    spy = PopenSpy()
    monkeypatch.setattr(cli.subprocess, "Popen", spy)
    monkeypatch.setattr(cli, "_wait_for_exit_file", lambda job_id, log_mode: 0)

    rc = main(["--global-log", "echo", "hello"])
    assert rc == 0

    runner_argv = spy.calls[0]
    assert "--global-log" in runner_argv

    sep = runner_argv.index("--")
    forwarded = runner_argv[sep + 1 :]
    assert forwarded == ["echo", "hello"]
