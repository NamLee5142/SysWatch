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
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import get_settings

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
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
    handler.setFormatter(logging.Formatter(FORMAT))
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
