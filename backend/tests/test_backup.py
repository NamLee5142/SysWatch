import sqlite3
import threading
from datetime import datetime, timezone

import pytest

from app.db.backup import (
    BackupFailed,
    build_parser,
    database_path,
    main,
    prune,
    run,
    timestamped_name,
    verify,
)


@pytest.fixture
def database(tmp_path):
    """A WAL database with a schema revision and a few hundred rows."""
    path = tmp_path / "syswatch.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, cpu REAL)")
    connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
    connection.execute("INSERT INTO alembic_version VALUES ('a1b2c3d4')")
    connection.executemany(
        "INSERT INTO snapshots (cpu) VALUES (?)", [(float(n),) for n in range(500)]
    )
    connection.commit()
    connection.close()
    return path


@pytest.fixture
def url(database):
    return f"sqlite:///{database.as_posix()}"


def rows(path, table="snapshots"):
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        connection.close()


def always_fails(path, expected):
    raise BackupFailed("corrupt")


def test_backup_copies_the_data(tmp_path, url, database):
    target = run(tmp_path / "backups", database_url=url)

    assert target.exists()
    assert rows(target) == rows(database)


def test_backup_is_verified_against_the_source_revision(tmp_path, url):
    target = run(tmp_path / "backups", database_url=url)

    connection = sqlite3.connect(target)
    try:
        found = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        connection.close()

    assert found == ("a1b2c3d4",)


def test_backup_has_no_wal_sidecar(tmp_path, url):
    """The reason for VACUUM INTO over a file copy.

    A copied WAL database is two files; leave one behind and the restore is
    silently missing recent writes.
    """
    target = run(tmp_path / "backups", database_url=url)

    assert not target.with_name(target.name + "-wal").exists()
    assert not target.with_name(target.name + "-shm").exists()

    connection = sqlite3.connect(target)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        connection.close()


def test_backup_is_consistent_while_the_database_is_written(tmp_path, url, database):
    """The plan's acceptance condition: taken live, restores and opens.

    A writer commits throughout the backup, which is what the poller does.
    """
    stop = threading.Event()
    failures = []

    def write():
        connection = sqlite3.connect(database, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            while not stop.is_set():
                connection.execute("INSERT INTO snapshots (cpu) VALUES (1.5)")
                connection.commit()
        except Exception as error:  # surfaced below rather than lost in a thread
            failures.append(error)
        finally:
            connection.close()

    writer = threading.Thread(target=write)
    writer.start()
    try:
        target = run(tmp_path / "backups", database_url=url)
    finally:
        stop.set()
        writer.join(timeout=10)

    assert failures == []
    # Consistent, not merely readable: a torn snapshot fails integrity_check.
    assert verify(target, "a1b2c3d4")
    assert rows(target) >= 500


def test_the_source_is_never_written_to(tmp_path, url, database):
    before = database.stat().st_mtime_ns

    run(tmp_path / "backups", database_url=url)

    assert database.stat().st_mtime_ns == before


def test_filenames_are_timestamped_and_sort_chronologically():
    earlier = timestamped_name(datetime(2026, 9, 4, 8, 30, 0, tzinfo=timezone.utc))
    later = timestamped_name(datetime(2026, 9, 4, 12, 5, 0, tzinfo=timezone.utc))

    assert earlier == "syswatch-20260904-083000.db"
    assert sorted([later, earlier]) == [earlier, later]


def test_a_second_backup_in_the_same_second_fails_rather_than_overwriting(tmp_path, url):
    moment = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
    run(tmp_path / "backups", database_url=url, now=moment)

    with pytest.raises(BackupFailed, match="already exists"):
        run(tmp_path / "backups", database_url=url, now=moment)


def test_retention_keeps_the_newest_and_deletes_the_rest(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    names = [f"syswatch-2026090{n}-120000.db" for n in range(1, 6)]
    for name in names:
        (directory / name).touch()

    removed = prune(directory, keep=2)

    assert [path.name for path in removed] == names[:3]
    assert sorted(path.name for path in directory.glob("*.db")) == names[3:]


def test_retention_never_touches_a_file_it_did_not_write(tmp_path):
    directory = tmp_path / "backups"
    directory.mkdir()
    (directory / "syswatch-20260901-120000.db").touch()
    (directory / "syswatch-20260902-120000.db").touch()
    bystander = directory / "important-notes.db"
    bystander.touch()
    live = directory / "syswatch.db"
    live.touch()

    prune(directory, keep=1)

    assert bystander.exists()
    assert live.exists()


def test_retention_is_off_by_default(tmp_path, url):
    directory = tmp_path / "backups"
    for hour in range(3):
        run(
            directory,
            database_url=url,
            now=datetime(2026, 9, 4, hour, tzinfo=timezone.utc),
        )

    assert len(list(directory.glob("*.db"))) == 3


def test_the_new_backup_is_never_the_one_pruned(tmp_path, url):
    directory = tmp_path / "backups"
    for hour in range(4):
        target = run(
            directory,
            keep=1,
            database_url=url,
            now=datetime(2026, 9, 4, hour, tzinfo=timezone.utc),
        )
        assert target.exists()

    assert [path.name for path in directory.glob("*.db")] == [
        "syswatch-20260904-030000.db"
    ]


def test_a_backup_that_fails_verification_is_deleted(tmp_path, url, monkeypatch):
    monkeypatch.setattr("app.db.backup.verify", always_fails)

    with pytest.raises(BackupFailed):
        run(tmp_path / "backups", database_url=url)

    # Leaving it would mean trusting it at restore time.
    assert list((tmp_path / "backups").glob("*.db")) == []


def test_a_failed_backup_does_not_age_out_a_good_one(tmp_path, url, monkeypatch):
    directory = tmp_path / "backups"
    good = run(
        directory, database_url=url, now=datetime(2026, 9, 4, tzinfo=timezone.utc)
    )

    monkeypatch.setattr("app.db.backup.verify", always_fails)
    with pytest.raises(BackupFailed):
        run(
            directory,
            keep=1,
            database_url=url,
            now=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )

    assert good.exists()


def test_verify_rejects_a_revision_mismatch(tmp_path, url):
    target = run(tmp_path / "backups", database_url=url)

    with pytest.raises(BackupFailed, match="schema revision"):
        verify(target, "a-different-revision")


def test_verify_rejects_a_corrupt_file(tmp_path, url):
    target = run(tmp_path / "backups", database_url=url)
    target.write_bytes(b"this is not a database")

    with pytest.raises(BackupFailed):
        verify(target, "a1b2c3d4")


def test_a_non_sqlite_database_is_refused(tmp_path):
    with pytest.raises(BackupFailed, match="Only SQLite"):
        run(tmp_path, database_url="postgresql://localhost/syswatch")


def test_a_missing_database_is_refused(tmp_path):
    url = f"sqlite:///{(tmp_path / 'absent.db').as_posix()}"

    with pytest.raises(BackupFailed, match="Nothing to back up"):
        run(tmp_path / "backups", database_url=url)


def test_an_in_memory_database_has_no_file_to_back_up():
    assert database_path("sqlite://") is None
    assert database_path("sqlite:///:memory:") is None


def test_the_destination_directory_is_created(tmp_path, url):
    target = run(tmp_path / "a" / "b" / "c", database_url=url)

    assert target.parent.is_dir()


def test_main_reports_success(tmp_path, url, monkeypatch, capsys):
    monkeypatch.setenv("SYSWATCH_DATABASE_URL", url)

    assert main([str(tmp_path / "backups")]) == 0
    assert "verified" in capsys.readouterr().out


def test_main_reports_failure_without_a_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SYSWATCH_DATABASE_URL", "postgresql://localhost/syswatch")

    assert main([str(tmp_path)]) == 1
    assert "Only SQLite" in capsys.readouterr().err


def test_keep_must_be_positive(tmp_path, capsys):
    assert main([str(tmp_path), "--keep", "0"]) == 1
    assert "at least 1" in capsys.readouterr().err


def test_the_parser_defaults_to_no_retention():
    assert build_parser().parse_args(["dest"]).keep is None
