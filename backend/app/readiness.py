"""Whether this process can actually do its job, as opposed to being alive.

`/api/health` answers "is this process running", which stays true while the
database is missing, the schema is three migrations behind and no account
exists. Something will eventually be configured to trust that answer, and a
supervisor restarting a healthy process fixes none of those. So the two
questions get two endpoints.
"""
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select, text

from app.db import get_session
from app.db.models import UserRecord
from config import get_settings

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    # Shown to an unauthenticated caller, so it says what to do rather than
    # what went wrong internally: an operator needs the instruction and nobody
    # else gains anything from it.
    detail: str = ""


@lru_cache(maxsize=1)
def expected_revision():
    """The migration revision this build of the code expects.

    Read from the migration scripts rather than hard-coded, so it cannot drift
    from what `alembic upgrade head` would apply.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    # Alembic announces each autogenerate plugin at INFO when its script
    # directory is first read. Useful when running a migration, seven lines of
    # noise in the log of the first health probe.
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


def check_database() -> Check:
    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        # Logged in full for the operator; the caller gets the short version.
        logger.warning("Readiness: the database is not reachable", exc_info=True)
        return Check("database", False, "the database is not reachable")

    return Check("database", True)


def check_schema() -> Check:
    try:
        with get_session() as session:
            applied = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        logger.warning("Readiness: no schema version could be read", exc_info=True)
        return Check("schema", False, "the schema is not initialised; run 'alembic upgrade head'")

    if applied != expected_revision():
        return Check("schema", False, "the schema is out of date; run 'alembic upgrade head'")

    return Check("schema", True)


def check_accounts() -> Check:
    if not get_settings().auth_enabled:
        # Nothing logs in, so nothing needs an account to log in with.
        return Check("accounts", True, "authentication is disabled")

    try:
        with get_session() as session:
            count = session.execute(select(func.count()).select_from(UserRecord)).scalar_one()
    except Exception:
        logger.warning("Readiness: accounts could not be counted", exc_info=True)
        return Check("accounts", False, "accounts could not be read")

    if not count:
        # An install that migrated but never bootstrapped: the API is up and
        # nobody on earth can log in to it.
        return Check("accounts", False, "no accounts exist; run 'python -m app.auth.create_admin'")

    return Check("accounts", True)


def readiness() -> tuple[bool, list[Check]]:
    """Run every check. Later ones still run when an earlier one fails, so one
    request reports everything that is wrong rather than the first thing."""
    checks = [check_database(), check_schema(), check_accounts()]
    return all(check.ok for check in checks), checks
