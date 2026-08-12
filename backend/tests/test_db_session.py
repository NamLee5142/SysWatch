import pytest
from sqlalchemy import text

from app.db import session as db_session


@pytest.fixture(autouse=True)
def reset_engine():
    db_session.dispose_engine()
    yield
    db_session.dispose_engine()


def sqlite_url(tmp_path, name="test.db"):
    # as_posix() keeps the Windows drive letter usable in a sqlite:/// URL.
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def test_engine_is_created_once(tmp_path):
    first = db_session.init_engine(sqlite_url(tmp_path))
    assert db_session.get_engine() is first
    # A second init must not replace the pool held by existing callers.
    assert db_session.init_engine(sqlite_url(tmp_path, "other.db")) is first


def test_get_engine_falls_back_to_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("SYSWATCH_DATABASE_URL", sqlite_url(tmp_path))
    engine = db_session.get_engine()
    assert engine.url.database.endswith("test.db")


def test_session_commits_on_success(tmp_path):
    db_session.init_engine(sqlite_url(tmp_path))

    with db_session.get_session() as session:
        session.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
        session.execute(text("INSERT INTO t (v) VALUES ('ok')"))

    with db_session.get_session() as session:
        assert session.execute(text("SELECT v FROM t")).scalar_one() == "ok"


def test_session_rolls_back_on_error(tmp_path):
    db_session.init_engine(sqlite_url(tmp_path))

    with db_session.get_session() as session:
        session.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))

    with pytest.raises(RuntimeError):
        with db_session.get_session() as session:
            session.execute(text("INSERT INTO t (v) VALUES ('doomed')"))
            raise RuntimeError("boom")

    with db_session.get_session() as session:
        assert session.execute(text("SELECT COUNT(*) FROM t")).scalar_one() == 0


def test_sqlite_runs_in_wal_mode(tmp_path):
    db_session.init_engine(sqlite_url(tmp_path))

    with db_session.get_session() as session:
        mode = session.execute(text("PRAGMA journal_mode")).scalar_one()

    assert mode.lower() == "wal"


def test_in_memory_url_shares_one_connection():
    db_session.init_engine("sqlite://")

    with db_session.get_session() as session:
        session.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))

    # Without StaticPool this second session would open a private database and
    # fail to find the table.
    with db_session.get_session() as session:
        assert session.execute(text("SELECT COUNT(*) FROM t")).scalar_one() == 0


def test_dispose_engine_allows_reinit(tmp_path):
    first = db_session.init_engine(sqlite_url(tmp_path))
    db_session.dispose_engine()
    second = db_session.init_engine(sqlite_url(tmp_path))

    assert first is not second
