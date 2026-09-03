"""The production entrypoint.

run.py reloads on every edit, which is exactly what a service manager must not
do. These check that this one carries none of that.
"""
import pytest
from fastapi import FastAPI

from serve import build_parser, main


class Recorder:
    """Stands in for uvicorn.run, capturing what it was asked to do."""

    def __init__(self):
        self.app = None
        self.kwargs = None

    def __call__(self, app, **kwargs):
        self.app = app
        self.kwargs = kwargs


@pytest.fixture
def run(database):
    return Recorder()


# --- what it serves ---------------------------------------------------------


def test_it_runs_the_application(run):
    assert main([], run=run) == 0

    # The app object rather than an import string: only reload and workers need
    # a string, and this supports neither.
    assert isinstance(run.app, FastAPI)


def test_reload_is_not_even_offered(run, monkeypatch):
    monkeypatch.setenv("SYSWATCH_HOST", "127.0.0.1")

    main([], run=run)

    # A service manager restarting the process because a file changed is not a
    # thing anyone asked for.
    assert "reload" not in run.kwargs


def test_uvicorn_is_told_to_leave_logging_alone(run):
    main([], run=run)

    # Its default log config replaces the handlers the application configured,
    # which is where the log file lands.
    assert run.kwargs["log_config"] is None


# --- host and port ----------------------------------------------------------


def test_it_binds_what_the_settings_say(run, monkeypatch):
    monkeypatch.setenv("SYSWATCH_HOST", "10.0.0.5")
    monkeypatch.setenv("SYSWATCH_PORT", "9001")

    main([], run=run)

    assert (run.kwargs["host"], run.kwargs["port"]) == ("10.0.0.5", 9001)


def test_the_command_line_overrides_the_settings(run, monkeypatch):
    monkeypatch.setenv("SYSWATCH_HOST", "10.0.0.5")
    monkeypatch.setenv("SYSWATCH_PORT", "9001")

    main(["--host", "127.0.0.1", "--port", "8123"], run=run)

    assert (run.kwargs["host"], run.kwargs["port"]) == ("127.0.0.1", 8123)


def test_it_defaults_to_loopback(run, monkeypatch):
    monkeypatch.delenv("SYSWATCH_HOST", raising=False)
    monkeypatch.delenv("SYSWATCH_PORT", raising=False)

    main([], run=run)

    assert (run.kwargs["host"], run.kwargs["port"]) == ("127.0.0.1", 8000)


# --- workers ----------------------------------------------------------------


def test_asking_for_workers_is_refused_with_a_reason(run, capsys):
    assert main(["--workers", "4"], run=run) == 1

    message = capsys.readouterr().err
    # Someone will try this. Silence, or an argparse "unrecognized argument",
    # tells them nothing about why one process is deliberate.
    assert "poller would run in every worker" in message
    assert "rate limit" in message
    assert "SQLite" in message
    assert run.kwargs is None


def test_asking_for_one_worker_is_just_fine(run):
    assert main(["--workers", "1"], run=run) == 0
    assert run.kwargs is not None


def test_the_flag_exists_so_it_can_be_refused():
    options = {
        option for action in build_parser()._actions for option in action.option_strings
    }

    # Left out of the parser, --workers would be an "unrecognized argument".
    assert "--workers" in options
