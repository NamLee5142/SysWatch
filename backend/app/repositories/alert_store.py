from datetime import datetime, timezone

from sqlalchemy import func, select, update

from app.db import get_session
from app.db.models import AlertRecord, AlertRuleRecord
from app.repositories.snapshot_store import from_storage_time, to_storage_time

DEFAULT_LIMIT = 100

FIRING = "firing"
RESOLVED = "ok"


def _now():
    """Naive UTC 'now', the shape the timestamps are stored in."""
    return to_storage_time(datetime.now(timezone.utc))


class AlertRuleStore:
    """Persistence boundary for alert rules. Keeps SQLAlchemy out of the callers."""

    def list(self):
        """Every rule, newest first."""
        statement = select(AlertRuleRecord).order_by(AlertRuleRecord.id.desc())

        with get_session() as session:
            rows = session.execute(statement).scalars().all()

        return [self._hydrate(row) for row in rows]

    def enabled_rules(self):
        """Only the enabled rules, in a stable order. What the engine evaluates."""
        statement = (
            select(AlertRuleRecord)
            .where(AlertRuleRecord.enabled.is_(True))
            .order_by(AlertRuleRecord.id)
        )

        with get_session() as session:
            rows = session.execute(statement).scalars().all()

        return [self._hydrate(row) for row in rows]

    def get(self, rule_id):
        with get_session() as session:
            row = session.get(AlertRuleRecord, rule_id)

        return self._hydrate(row)

    def create(self, data):
        """Insert a rule from anything with the AlertRuleCreate attributes."""
        now = _now()
        record = AlertRuleRecord(
            name=data.name,
            metric=data.metric,
            operator=data.operator,
            threshold=data.threshold,
            severity=data.severity,
            enabled=data.enabled,
            created_at=now,
            updated_at=now,
        )

        with get_session() as session:
            session.add(record)

        return self._hydrate(record)

    def update(self, rule_id, changes):
        """Apply a dict of field -> value. Returns the updated rule, or None.

        The caller passes only the fields it means to change (an
        AlertRuleUpdate dumped with exclude_unset); `updated_at` is bumped here.
        """
        with get_session() as session:
            record = session.get(AlertRuleRecord, rule_id)
            if record is None:
                return None

            for field, value in changes.items():
                setattr(record, field, value)
            record.updated_at = _now()

        return self._hydrate(record)

    def delete(self, rule_id):
        """Hard delete. Returns False when the rule was already gone.

        Open alerts survive with rule_id set NULL (the FK's ON DELETE SET NULL,
        which PRAGMA foreign_keys=ON makes SQLite honour).
        """
        with get_session() as session:
            record = session.get(AlertRuleRecord, rule_id)
            if record is None:
                return False
            session.delete(record)

        return True

    def _hydrate(self, record):
        if record is None:
            return None

        record.created_at = from_storage_time(record.created_at)
        record.updated_at = from_storage_time(record.updated_at)
        return record


class AlertStore:
    """Persistence boundary for alerts — the open ones and the resolved history."""

    def active(self, host_name=None):
        """Firing alerts, newest first. host_name=None spans every host."""
        statement = select(AlertRecord).where(AlertRecord.state == FIRING)

        if host_name is not None:
            statement = statement.where(AlertRecord.host_name == host_name)

        statement = statement.order_by(
            AlertRecord.triggered_at.desc(), AlertRecord.id.desc()
        )

        with get_session() as session:
            rows = session.execute(statement).scalars().all()

        return [self._hydrate(row) for row in rows]

    def open_alert(self, rule_id, host_name):
        """The current firing alert for this (rule, host), or None.

        Ordered by id DESC: a (rule, host) pair accumulates resolved history and
        only the newest row can still be open.
        """
        statement = (
            select(AlertRecord)
            .where(
                AlertRecord.rule_id == rule_id,
                AlertRecord.host_name == host_name,
                AlertRecord.state == FIRING,
            )
            .order_by(AlertRecord.id.desc())
            .limit(1)
        )

        with get_session() as session:
            row = session.execute(statement).scalars().first()

        return self._hydrate(row)

    def open_new(self, *, rule, host_name, value, at):
        """Open a firing alert, copying the rule's identity onto the row."""
        stored_at = to_storage_time(at)
        record = AlertRecord(
            rule_id=rule.id,
            rule_name=rule.name,
            metric=rule.metric,
            operator=rule.operator,
            threshold=rule.threshold,
            severity=rule.severity,
            host_name=host_name,
            state=FIRING,
            value=value,
            triggered_at=stored_at,
            resolved_at=None,
            last_seen_at=stored_at,
        )

        with get_session() as session:
            session.add(record)

        return self._hydrate(record)

    def touch(self, *, alert_id, value, at):
        """Refresh a still-firing alert's value and last-seen time."""
        statement = (
            update(AlertRecord)
            .where(AlertRecord.id == alert_id)
            .values(value=value, last_seen_at=to_storage_time(at))
        )

        with get_session() as session:
            session.execute(statement)

    def resolve(self, *, alert_id, value, at):
        """Close an alert: state -> ok, resolved_at stamped.

        Returns the closed alert, like open_new returns the opened one. A
        caller announcing the resolution needs the resolved row: the one it
        held before this call still says it is firing.
        """
        stored_at = to_storage_time(at)
        statement = (
            update(AlertRecord)
            .where(AlertRecord.id == alert_id)
            .values(
                state=RESOLVED,
                value=value,
                resolved_at=stored_at,
                last_seen_at=stored_at,
            )
        )

        with get_session() as session:
            session.execute(statement)

        return self.get(alert_id)

    def get(self, alert_id):
        with get_session() as session:
            row = session.get(AlertRecord, alert_id)

        return self._hydrate(row)

    def query(self, host_name=None, state=None, rule_id=None, since=None, until=None,
              limit=DEFAULT_LIMIT, offset=0):
        """Alerts newest first, filtered by host, state, rule and trigger time."""
        statement = self._filtered(
            select(AlertRecord), host_name, state, rule_id, since, until
        )
        statement = (
            statement.order_by(AlertRecord.triggered_at.desc(), AlertRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )

        with get_session() as session:
            rows = session.execute(statement).scalars().all()

        return [self._hydrate(row) for row in rows]

    def count(self, host_name=None, state=None, rule_id=None, since=None, until=None):
        """How many alerts match, ignoring paging — shared filters with query()."""
        statement = self._filtered(
            select(func.count()).select_from(AlertRecord),
            host_name,
            state,
            rule_id,
            since,
            until,
        )

        with get_session() as session:
            return session.execute(statement).scalar_one()

    def _filtered(self, statement, host_name, state, rule_id, since, until):
        if host_name is not None:
            statement = statement.where(AlertRecord.host_name == host_name)
        if state is not None:
            statement = statement.where(AlertRecord.state == state)
        if rule_id is not None:
            statement = statement.where(AlertRecord.rule_id == rule_id)
        if since is not None:
            statement = statement.where(AlertRecord.triggered_at >= to_storage_time(since))
        if until is not None:
            statement = statement.where(AlertRecord.triggered_at <= to_storage_time(until))

        return statement

    def _hydrate(self, record):
        """Hand back UTC-aware times, like SnapshotStore does."""
        if record is None:
            return None

        record.triggered_at = from_storage_time(record.triggered_at)
        record.resolved_at = from_storage_time(record.resolved_at)
        record.last_seen_at = from_storage_time(record.last_seen_at)
        return record
