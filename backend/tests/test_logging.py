"""Where log lines go, and what must never be in them.

A Windows Service has no console: anything written to stderr goes nowhere,
including the reason it failed to start. The file is the one that matters.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler

import pytest
from fastapi.testclient import TestClient

from app import logging_config
from app.auth.password import hash_password
from app.logging_config import BACKUP_COUNT, LOG_FILE_NAME, MAX_BYTES, configure_logging
from app.main import create_app
from app.repositories import UserStore
from config import Settings

PASSWORD = "correct horse Battery staple"


@pytest.fixture(autouse=True)
def restore_root_logging():
    """configure_logging() reaches into the root logger, which outlives a test."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level

    yield

    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    for handler in handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(level)


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    directory = tmp_path / "logs"
    monkeypatch.setenv("SYSWATCH_LOG_DIR", str(directory))
    return directory


def our_handlers():
    return [h for h in logging.getLogger().handlers if getattr(h, "_syswatch_handler", False)]


# --- handlers ---------------------------------------------------------------


def test_it_writes_to_a_file(log_dir):
    path = configure_logging(Settings())

    logging.getLogger("test").info("a line worth keeping")

    assert path == log_dir / LOG_FILE_NAME
    assert "a line worth keeping" in path.read_text(encoding="utf-8")


def test_the_directory_is_created(log_dir):
    assert not log_dir.exists()

    configure_logging(Settings())

    assert log_dir.is_dir()


def test_the_file_rotates_rather_than_growing_forever(log_dir):
    configure_logging(Settings())

    rotating = [h for h in our_handlers() if isinstance(h, RotatingFileHandler)]

    # Bounded, so an unattended service cannot fill a disk.
    assert len(rotating) == 1
    assert (rotating[0].maxBytes, rotating[0].backupCount) == (MAX_BYTES, BACKUP_COUNT)


def test_the_console_is_kept_when_there_is_one(log_dir):
    configure_logging(Settings())

    streams = [h for h in our_handlers() if isinstance(h, logging.StreamHandler)
               and not isinstance(h, RotatingFileHandler)]
    assert streams


def test_no_console_handler_without_a_stderr(log_dir, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)

    configure_logging(Settings())

    # Under a service host stderr is not a stream that goes unread — writing to
    # it raises.
    streams = [h for h in our_handlers() if not isinstance(h, RotatingFileHandler)]
    assert streams == []


def test_calling_it_twice_does_not_double_every_line(log_dir):
    configure_logging(Settings())
    before = len(our_handlers())

    configure_logging(Settings())

    assert len(our_handlers()) == before


def test_it_leaves_other_handlers_alone(log_dir):
    root = logging.getLogger()
    borrowed = logging.NullHandler()
    root.addHandler(borrowed)

    configure_logging(Settings())
    configure_logging(Settings())

    # pytest's capture handler lives here too; removing it would break caplog
    # in every test that also configures logging.
    assert borrowed in root.handlers
    root.removeHandler(borrowed)


# --- level ------------------------------------------------------------------


@pytest.mark.parametrize("configured, expected", [("DEBUG", logging.DEBUG), ("warning", logging.WARNING)])
def test_the_level_comes_from_the_settings(log_dir, monkeypatch, configured, expected):
    monkeypatch.setenv("SYSWATCH_LOG_LEVEL", configured)

    configure_logging(Settings())

    assert logging.getLogger().level == expected


def test_a_nonsense_level_falls_back_to_info(log_dir, monkeypatch):
    monkeypatch.setenv("SYSWATCH_LOG_LEVEL", "chatty")

    configure_logging(Settings())

    # Refusing to start over a typo in a log level would be worse than the typo.
    assert logging.getLogger().level == logging.INFO


# --- failure ----------------------------------------------------------------


def test_an_unusable_log_directory_does_not_stop_anything(tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "logs"
    blocker.write_text("this is a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("SYSWATCH_LOG_DIR", str(blocker))

    with caplog.at_level(logging.WARNING):
        path = configure_logging(Settings())

    # Worth complaining about; not worth refusing to monitor anything over.
    assert path is None
    assert "logging to the console only" in caplog.text


# --- the rule app/auth exists to keep ----------------------------------------


def test_logging_in_writes_no_secret_to_the_log(log_dir, monkeypatch, database):
    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "true")
    monkeypatch.setenv("SYSWATCH_SESSION_SECRET", "test-secret-long-enough-for-the-startup-check")
    # Everything the application is willing to say, so nothing is hidden by a
    # level that happens to be too high.
    monkeypatch.setenv("SYSWATCH_LOG_LEVEL", "DEBUG")

    UserStore().create(username="root", password_hash=hash_password(PASSWORD), role="admin")
    path = configure_logging(Settings())

    client = TestClient(create_app(), base_url="https://testserver/api")
    response = client.post("/auth/login", json={"username": "root", "password": PASSWORD})
    assert response.status_code == 200
    token = client.cookies.get("syswatch_session")
    client.get("/alerts")
    client.post("/auth/logout")

    logging.shutdown()
    written = path.read_text(encoding="utf-8", errors="replace")

    # app/auth has no logger at all, precisely so this stays true.
    assert PASSWORD not in written
    assert token not in written
    assert "hunter" not in written.lower()
    for word in PASSWORD.split():
        assert word not in written


def test_a_failed_login_writes_no_password_either(log_dir, monkeypatch, database):
    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "true")
    monkeypatch.setenv("SYSWATCH_SESSION_SECRET", "test-secret-long-enough-for-the-startup-check")
    monkeypatch.setenv("SYSWATCH_LOG_LEVEL", "DEBUG")

    UserStore().create(username="root", password_hash=hash_password(PASSWORD), role="admin")
    path = configure_logging(Settings())

    attempted = "the wrong Password 12345"
    client = TestClient(create_app(), base_url="https://testserver/api")
    assert client.post(
        "/auth/login", json={"username": "root", "password": attempted}
    ).status_code == 401

    logging.shutdown()

    # The one someone typed by mistake is still someone's password somewhere.
    assert attempted not in path.read_text(encoding="utf-8", errors="replace")
