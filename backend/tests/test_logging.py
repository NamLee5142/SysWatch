"""Where log lines go, and what must never be in them.

A Windows Service has no console: anything written to stderr goes nowhere,
including the reason it failed to start. The file is the one that matters.
"""
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

import pytest
from fastapi.testclient import TestClient

from app import logging_config
from app.auth.password import hash_password
from app.logging_config import (
    BACKUP_COUNT,
    DATE_FORMAT,
    FORMAT,
    LOG_FILE_NAME,
    MAX_BYTES,
    UtcFormatter,
    configure_logging,
)
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


def test_per_request_chatter_is_silenced(log_dir):
    """Loggers that emit one line per successful call are held to WARNING.

    The poller calls the agent every SYSWATCH_POLL_INTERVAL_SECONDS forever.
    At the default ten seconds, httpx's per-request INFO line is 8,640 entries
    a day; on the first real deployment it outnumbered every application
    logger combined. Failures still arrive - the poller reports those itself,
    with the context httpx does not have.
    """
    configure_logging(Settings())

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("uvicorn.access").level == logging.WARNING


def test_silencing_chatter_does_not_hide_its_failures(log_dir):
    configure_logging(Settings())
    path = log_dir / "syswatch.log"

    logging.getLogger("httpx").info("HTTP Request: GET /snapshot 200 OK")
    logging.getLogger("httpx").warning("HTTP Request: GET /snapshot 503")
    logging.shutdown()

    written = path.read_text(encoding="utf-8", errors="replace")
    assert "200 OK" not in written
    assert "503" in written


# --- what time it is --------------------------------------------------------
#
# Everything this application stores is UTC. The log was the one thing writing
# local time, which put the same instant seven hours from itself on the machine
# these were written on.

# The leading stamp of a log line: 2026-09-06T04:18:16.169Z
STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3})Z ")


def stamp_of(line):
    """The instant a log line claims to have been written."""
    found = STAMP.match(line)
    assert found, f"no ISO 8601 UTC stamp at the start of {line!r}"
    return datetime.fromisoformat(found.group(1)).replace(tzinfo=timezone.utc)


def test_a_log_line_is_stamped_in_utc(log_dir):
    path = configure_logging(Settings())
    before = datetime.now(timezone.utc)

    logging.getLogger("test").info("what time is it")

    written = stamp_of(path.read_text(encoding="utf-8").splitlines()[-1])
    assert before - timedelta(seconds=5) <= written <= datetime.now(timezone.utc) + timedelta(seconds=5)


def test_the_stamp_is_the_utc_spelling_and_not_the_local_one():
    """Independent of where the suite runs, which is the point.

    A fixed instant has one UTC spelling; asserting it exactly means a machine
    whose clock is set to Ho Chi Minh City and one set to UTC produce the same
    line, and a formatter that quietly reverted to localtime fails on the
    former.
    """
    record = logging.LogRecord(
        name="app.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="fixed", args=(), exc_info=None,
    )
    # 2026-09-06 11:30:45.123 UTC, as a POSIX timestamp.
    record.created = 1788694245.123
    record.msecs = 123.0

    formatted = UtcFormatter(FORMAT, datefmt=DATE_FORMAT).format(record)

    assert formatted == "2026-09-06T11:30:45.123Z INFO app.test: fixed"


def test_the_handlers_actually_use_it(log_dir):
    """The formatter is only worth having if it is installed on both."""
    configure_logging(Settings())

    for handler in our_handlers():
        assert handler.formatter.converter is time.gmtime


def test_a_log_line_and_the_snapshot_it_describes_name_the_same_instant(
    log_dir, database
):
    """The condition this change exists to satisfy.

    Reading a support bundle means lining a log line up against the row it is
    about. While the log was local and collectedAt was UTC that was timezone
    arithmetic done by hand, during an incident. Now it is a string comparison.
    """
    from app.models.snapshot import Snapshot
    from app.repositories import SnapshotStore

    path = configure_logging(Settings())

    collected_at = datetime.now(timezone.utc)
    stored = SnapshotStore().save(
        Snapshot.from_payload(
            {
                "collectedAt": collected_at.isoformat(),
                "cpuInfo": {"coreCount": 8, "usagePercent": 12.5},
                "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
                "diskInfo": {"totalGB": 512, "freeGB": 120},
                "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
            }
        )
    )
    logging.getLogger("app.services.snapshot_poller").info(
        "Stored a snapshot from devbox"
    )

    logged = stamp_of(path.read_text(encoding="utf-8").splitlines()[-1])

    # Same clock: the gap is how long the two lines above took, not an offset.
    assert abs(logged - stored.collected_at) < timedelta(seconds=5)

    # And the same spelling, so grep works across the two.
    assert logged.isoformat().startswith(stored.collected_at.isoformat()[:13])
