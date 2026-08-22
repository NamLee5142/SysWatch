from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config import get_settings

# The engine owns a connection pool and must exist once per process, not once
# per request. get_settings() builds a fresh Settings on every call, so the URL
# is read here and the result cached rather than re-resolved by callers.
_engine = None
_session_factory = None


def _is_sqlite(database_url):
    return database_url.startswith("sqlite")


def _is_in_memory(database_url):
    return ":memory:" in database_url or database_url == "sqlite://"


def _engine_kwargs(database_url):
    if not _is_sqlite(database_url):
        return {}

    # FastAPI runs sync routes in a threadpool and the snapshot poller runs on
    # its own thread, so connections outlive the thread that opened them.
    kwargs = {"connect_args": {"check_same_thread": False}}

    if _is_in_memory(database_url):
        # Every pooled connection to ":memory:" gets a private database, which
        # makes an in-memory engine useless unless all sessions share one.
        kwargs["poolclass"] = StaticPool

    return kwargs


def _configure_sqlite(engine):
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # WAL lets the API read while the poller writes; on the default journal
        # mode that combination fails with "database is locked".
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def init_engine(database_url=None):
    """Create the process-wide engine. Idempotent, so repeat calls are cheap."""
    global _engine, _session_factory

    if _engine is not None:
        return _engine

    url = database_url or get_settings().database_url
    _engine = create_engine(url, **_engine_kwargs(url))

    if _is_sqlite(url):
        _configure_sqlite(_engine)

    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine():
    """Return the process-wide engine, creating it on first use."""
    if _engine is None:
        return init_engine()
    return _engine


def dispose_engine():
    """Close pooled connections and clear the engine, for shutdown and tests."""
    global _engine, _session_factory

    if _engine is not None:
        _engine.dispose()

    _engine = None
    _session_factory = None


@contextmanager
def get_session():
    """Session scope that commits on success and rolls back on failure."""
    if _session_factory is None:
        init_engine()

    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
