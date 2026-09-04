r"""Back up the snapshot database.

    python -m app.db.backup C:\ProgramData\SysWatch\backups

`VACUUM INTO` rather than a file copy. In WAL mode the database is two files:
recent commits live in the `-wal` sidecar until a checkpoint folds them back,
so copying `syswatch.db` on its own yields a file that is missing whatever had
not been checkpointed — silently, and only discovered at restore. `VACUUM INTO`
asks SQLite for a consistent snapshot instead, which it can produce while the
poller is mid-write, and writes it as a single self-contained file in `delete`
journal mode with no sidecar to lose.

The destination is a directory and the filename is generated, because a
backup command whose output path is chosen by the caller eventually overwrites
the previous backup with a corrupt one. `VACUUM INTO` refuses to write over an
existing file, which makes the timestamp collision an error rather than a loss.

Every backup carries password hashes and session token hashes. The directory
inherits its permissions from wherever it is created; on Windows, keep it under
ProgramData rather than anywhere world-readable.
"""
import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from config import get_settings

FILENAME_PREFIX = "syswatch-"
FILENAME_SUFFIX = ".db"
# Matches what timestamped_name() produces and nothing else, so pruning can
# never reach a file this command did not write.
FILENAME_GLOB = f"{FILENAME_PREFIX}????????-??????{FILENAME_SUFFIX}"

NOT_SQLITE = (
    "Only SQLite databases can be backed up with this command. "
    "The configured database is {url!r}."
)
NO_DATABASE = "No database at {path}. Nothing to back up."


class BackupFailed(Exception):
    """The backup did not produce a verified file."""


def database_path(database_url):
    """The file backing a SQLite URL, or None for anything else."""
    url = make_url(database_url)

    if not url.drivername.startswith("sqlite"):
        return None

    # ":memory:" and "sqlite://" have no file behind them.
    if not url.database or url.database == ":memory:":
        return None

    return Path(url.database)


def timestamped_name(now=None):
    moment = now or datetime.now(timezone.utc)
    return f"{FILENAME_PREFIX}{moment.strftime('%Y%m%d-%H%M%S')}{FILENAME_SUFFIX}"


def schema_revision(connection):
    """The alembic revision a database is at, or None if it has no table."""
    try:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.DatabaseError:
        return None

    return row[0] if row else None


def verify(path, expected_revision):
    """Open a finished backup and confirm it is usable.

    An unverified backup is a hope rather than a backup. This is the same check
    a restore would make, run now while the original is still available.
    """
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as error:
        raise BackupFailed(f"{path.name} cannot be opened: {error}") from error

    try:
        # sqlite3.connect() opens lazily and succeeds on a file that is not a
        # database at all, so the read has to be guarded too. Unguarded, a
        # corrupt backup escaped as a raw DatabaseError: run() would not have
        # deleted it, and the command would have printed a traceback.
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.DatabaseError as error:
            raise BackupFailed(f"{path.name} is not readable: {error}") from error

        if integrity != "ok":
            raise BackupFailed(f"{path.name} failed its integrity check: {integrity}")

        found = schema_revision(connection)
        if found != expected_revision:
            raise BackupFailed(
                f"{path.name} is at schema revision {found!r}, "
                f"but the database is at {expected_revision!r}."
            )
    finally:
        connection.close()

    return True


def prune(directory, keep):
    """Delete all but the newest `keep` backups. Returns what was removed.

    Sorted by name, which for this fixed-width UTC timestamp is chronological
    and does not depend on a filesystem mtime that a copy would not preserve.
    """
    if keep is None:
        return []

    existing = sorted(directory.glob(FILENAME_GLOB))
    doomed = existing[: max(len(existing) - keep, 0)]

    for path in doomed:
        path.unlink()

    return doomed


def run(destination, keep=None, database_url=None, now=None):
    """Write a verified backup into `destination`. Returns its path."""
    url = database_url or get_settings().database_url
    source = database_path(url)

    if source is None:
        raise BackupFailed(NOT_SQLITE.format(url=url))

    if not source.exists():
        raise BackupFailed(NO_DATABASE.format(path=source))

    directory = Path(destination)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / timestamped_name(now)

    # Read-only: a backup must not be able to modify the thing it is backing
    # up, and this makes that structural rather than a matter of care.
    connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        expected = schema_revision(connection)
        try:
            connection.execute("VACUUM INTO ?", (str(target),))
        except sqlite3.OperationalError as error:
            raise BackupFailed(f"Could not write {target}: {error}") from error
    finally:
        connection.close()

    try:
        verify(target, expected)
    except BackupFailed:
        # A file that failed verification is worse than no file: it would be
        # trusted at restore time. Prune must not be reached either, or a bad
        # backup would age out a good one.
        target.unlink(missing_ok=True)
        raise

    prune(directory, keep)
    return target


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m app.db.backup",
        description="Write a consistent backup of the SysWatch database.",
    )
    parser.add_argument(
        "destination",
        help="Directory to write into. Created if it does not exist.",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=None,
        metavar="N",
        help="Keep only the newest N backups, deleting older ones. "
        "Off by default: deleting backups is not something to do by accident.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.keep is not None and args.keep < 1:
        print("--keep must be at least 1.", file=sys.stderr)
        return 1

    try:
        target = run(args.destination, keep=args.keep)
    except BackupFailed as failure:
        print(str(failure), file=sys.stderr)
        return 1

    size = target.stat().st_size
    print(f"Wrote {target} ({size:,} bytes), verified.")

    remaining = sorted(Path(args.destination).glob(FILENAME_GLOB))
    print(f"{len(remaining)} backup(s) in {args.destination}.")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
