from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from app.db import get_session
from app.db.models import SessionRecord, UserRecord
from app.repositories.snapshot_store import from_storage_time, to_storage_time


def _now():
    """Naive UTC 'now', the shape the timestamps are stored in."""
    return to_storage_time(datetime.now(timezone.utc))


class UserStore:
    """Persistence boundary for accounts. Keeps SQLAlchemy out of the callers."""

    def by_username(self, username):
        """The account for a login name, or None. The unique index serves this."""
        statement = select(UserRecord).where(UserRecord.username == username)

        with get_session() as session:
            record = session.execute(statement).scalars().first()

        return self._hydrate(record)

    def get(self, user_id):
        with get_session() as session:
            record = session.get(UserRecord, user_id)

        return self._hydrate(record)

    def create(self, username, password_hash, role="viewer", enabled=True):
        """Insert an account. The caller has already hashed the password."""
        now = _now()
        record = UserRecord(
            username=username,
            password_hash=password_hash,
            role=role,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )

        with get_session() as session:
            session.add(record)

        return self._hydrate(record)

    def _hydrate(self, record):
        if record is None:
            return None

        record.created_at = from_storage_time(record.created_at)
        record.updated_at = from_storage_time(record.updated_at)
        return record


class SessionStore:
    """Persistence boundary for sessions. Only ever sees hashed tokens."""

    def create(self, token_hash, user_id, expires_at):
        now = _now()
        record = SessionRecord(
            token_hash=token_hash,
            user_id=user_id,
            expires_at=to_storage_time(expires_at),
            created_at=now,
            last_seen_at=now,
        )

        with get_session() as session:
            session.add(record)

        return self._hydrate(record)

    def by_token_hash(self, token_hash):
        """The session a cookie resolves to, or None. Unique index lookup."""
        statement = select(SessionRecord).where(SessionRecord.token_hash == token_hash)

        with get_session() as session:
            record = session.execute(statement).scalars().first()

        return self._hydrate(record)

    def touch(self, session_id, at=None):
        """Record activity. Deliberately does not move expires_at."""
        statement = (
            update(SessionRecord)
            .where(SessionRecord.id == session_id)
            .values(last_seen_at=to_storage_time(at) if at is not None else _now())
        )

        with get_session() as session:
            session.execute(statement)

    def delete(self, session_id):
        """Drop one session. Returns whether a row went."""
        statement = delete(SessionRecord).where(SessionRecord.id == session_id)

        with get_session() as session:
            return session.execute(statement).rowcount > 0

    def prune_expired(self, now=None):
        """Delete sessions past their expiry. Returns rows removed.

        Expiry is enforced on read, so this is housekeeping rather than a
        security control — it keeps the table from growing a row per login
        forever.
        """
        cutoff = to_storage_time(now) if now is not None else _now()
        statement = delete(SessionRecord).where(SessionRecord.expires_at <= cutoff)

        with get_session() as session:
            return session.execute(statement).rowcount

    def _hydrate(self, record):
        if record is None:
            return None

        record.expires_at = from_storage_time(record.expires_at)
        record.created_at = from_storage_time(record.created_at)
        record.last_seen_at = from_storage_time(record.last_seen_at)
        return record
