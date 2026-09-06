"""Where the backend's log lines go.

A Windows Service has no console attached: anything written to stderr goes
nowhere, including the reason it failed to start. So the file handler is the
one that matters, and the console handler is the convenience.

Nothing in this application logs a password, a session token or a token hash —
see app/auth/, which has no logger at all for that reason. test_logging.py
enforces it by logging in and then grepping the file.
"""
import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import get_settings

# ISO 8601, in UTC, with the offset spelled out.
#
# Not a style preference. Everything this application stores is UTC - the
# database columns, the API's collectedAt, the alert timestamps - and the log
# was the one thing writing local time. On a machine seven hours off UTC the
# same instant appeared twice with a seven-hour gap between the two spellings,
# and correlating a log line with the snapshot it describes meant doing the
# arithmetic in your head, during an incident. It misled the author of this
# comment with both values on screen.
#
# The shape matches what the API serves, so a log line and a collectedAt can be
# compared by eye or by grep.
FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class UtcFormatter(logging.Formatter):
    """logging.Formatter, but the clock is UTC.

    logging uses time.localtime by default and offers no setting for this; the
    converter is the documented way to change it.
    """

    converter = time.gmtime


LOG_FILE_NAME = "syswatch.log"

# 5 MB before rolling, five kept: enough to cover the run-up to an incident on
# a chatty day, bounded so an unattended service cannot fill a disk.
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

# Marks the handlers this module installed, so repeat calls replace only those
# and leave anything else — pytest's capture handler, for one — alone.
_OURS = "_syswatch_handler"


def _remove_our_handlers(root):
    for handler in list(root.handlers):
        if getattr(handler, _OURS, False):
            root.removeHandler(handler)
            handler.close()


def _mark(handler):
    setattr(handler, _OURS, True)
    handler.setFormatter(UtcFormatter(FORMAT, datefmt=DATE_FORMAT))
    return handler


# Spelled out rather than read from logging.getLevelNamesMapping(), which
# arrived in 3.11 - two releases after the 3.10 the installer accepts. Being
# explicit also keeps the accepted values to the ones syswatch.env.example
# documents, instead of whatever names happen to be registered.
LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def configure_logging(settings=None):
    """Install the console and file handlers. Safe to call more than once."""
    settings = settings or get_settings()
    level = LEVELS.get(settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    _remove_our_handlers(root)
    root.setLevel(level)

    # None under pythonw and under a service host, where writing to it would
    # raise rather than simply go unread.
    if sys.stderr is not None:
        root.addHandler(_mark(logging.StreamHandler(sys.stderr)))

    log_file = add_file_handler(root, settings)

    # Access logs are one line per request and say nothing a failure does not.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # The same argument, outbound. httpx logs a line per request, and the
    # poller calls the agent every SYSWATCH_POLL_INTERVAL_SECONDS forever: at
    # the default ten seconds that is 8,640 lines a day reporting that the
    # thing that works, worked. On the first real deployment it was 8,432 of
    # the 11,300 lines in the log, more than every application logger put
    # together, and it buries the ones that mean something.
    #
    # Nothing is lost by silencing it. A poll that fails is reported by
    # app.services.snapshot_poller, which knows what the request was for;
    # httpx only knows that a GET happened.
    #
    # It has since acquired a second job. httpx logs the full URL of every
    # request, and a webhook URL is usually a credential - Slack, Discord and
    # Teams all put a token in the path. So this line is what keeps that token
    # out of the log file, and lowering it to debug a request publishes the
    # token as well. See app/alerts/webhook.py.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    return log_file


def add_file_handler(root, settings):
    """Attach the rotating file handler. Returns its path, or None.

    A log directory that cannot be created or written is worth complaining
    about, but it is not worth refusing to monitor anything over.
    """
    try:
        directory = Path(settings.log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / LOG_FILE_NAME

        handler = RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        root.addHandler(_mark(handler))
        return path
    except OSError as error:
        logging.getLogger(__name__).warning(
            "Could not open a log file in %s (%s); logging to the console only.",
            settings.log_dir,
            error,
        )
        return None
