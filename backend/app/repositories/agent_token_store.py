"""Persistence for agent credentials. Only ever sees hashed tokens.

The plaintext is produced by app/auth/agent_token.py, shown once, and never
reaches this module - every method here takes or returns a hash.
"""
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.db import get_session
from app.db.models import AgentTokenRecord
from app.repositories.snapshot_store import from_storage_time, to_storage_time


def _now():
    """Naive UTC 'now', the shape the timestamps are stored in."""
    return to_storage_time(datetime.now(timezone.utc))


class AgentTokenStore:
    def create(self, host_name, token_hash, description=None, at=None):
        """Record a credential for a host. Returns the stored row."""
        record = AgentTokenRecord(
            host_name=host_name,
            token_hash=token_hash,
            description=description,
            created_at=to_storage_time(at) if at is not None else _now(),
            last_seen_at=None,
            enabled=True,
        )

        with get_session() as session:
            session.add(record)

        return self._hydrate(record)

    def by_token_hash(self, token_hash):
        """The credential a hash resolves to, or None. Unique index lookup.

        Returns disabled rows too. Whether a disabled credential is refused is
        the caller's decision to make and to test, and hiding the row here
        would make "revoked" indistinguishable from "never existed" in a log.
        """
        statement = select(AgentTokenRecord).where(
            AgentTokenRecord.token_hash == token_hash
        )

        with get_session() as session:
            record = session.execute(statement).scalars().first()

        return self._hydrate(record)

    def get(self, token_id):
        with get_session() as session:
            record = session.get(AgentTokenRecord, token_id)
            if record is not None:
                session.expunge(record)

        return self._hydrate(record)

    def for_host(self, host_name):
        """Every credential issued to a host, newest first.

        More than one is normal during a rotation - see the note on
        AgentTokenRecord about why host_name is not unique.
        """
        statement = (
            select(AgentTokenRecord)
            .where(AgentTokenRecord.host_name == host_name)
            .order_by(AgentTokenRecord.created_at.desc(), AgentTokenRecord.id.desc())
        )

        with get_session() as session:
            records = session.execute(statement).scalars().all()
            for record in records:
                session.expunge(record)

        return [self._hydrate(record) for record in records]

    def all(self):
        """Every credential, newest first. For an operator listing them."""
        statement = select(AgentTokenRecord).order_by(
            AgentTokenRecord.created_at.desc(), AgentTokenRecord.id.desc()
        )

        with get_session() as session:
            records = session.execute(statement).scalars().all()
            for record in records:
                session.expunge(record)

        return [self._hydrate(record) for record in records]

    def set_enabled(self, token_id, enabled):
        """Revoke, or restore. Returns the row, or None if there is no such id.

        Revoking does not delete: a disabled row is the record that a
        decommissioned machine once had a credential, which is what an audit
        asks for and a missing row cannot answer.
        """
        statement = (
            update(AgentTokenRecord)
            .where(AgentTokenRecord.id == token_id)
            .values(enabled=enabled)
        )

        with get_session() as session:
            session.execute(statement)

        return self.get(token_id)

    def touch(self, token_id, at=None):
        """Record that this credential was used."""
        statement = (
            update(AgentTokenRecord)
            .where(AgentTokenRecord.id == token_id)
            .values(last_seen_at=to_storage_time(at) if at is not None else _now())
        )

        with get_session() as session:
            session.execute(statement)

    def _hydrate(self, record):
        if record is None:
            return None

        record.created_at = from_storage_time(record.created_at)
        record.last_seen_at = from_storage_time(record.last_seen_at)
        return record
