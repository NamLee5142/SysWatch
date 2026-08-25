from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.db import get_session
from app.db.models import SnapshotRecord

DEFAULT_LIMIT = 100


@dataclass(frozen=True)
class HostSummary:
    """One host's activity, aggregated over its snapshots.

    Not a SnapshotRecord: every field here is computed across many rows, so
    handing back an ORM instance would imply a row that does not exist.
    """

    host_name: str
    last_collected_at: datetime
    snapshot_count: int


def to_storage_time(value):
    """Normalise a datetime to naive UTC for storage.

    SQLite keeps no offset, so an aware value written as-is would come back
    stripped of its timezone and be read as though it were UTC. Converting here
    means the stored number is always UTC regardless of the caller's timezone.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def from_storage_time(value):
    """Re-tag a stored naive datetime as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SnapshotStore:
    """Persistence boundary for snapshots. Keeps SQLAlchemy out of the callers."""

    def save(self, snapshot):
        """Persist a snapshot.

        Returns the stored record, or None when this host already has a snapshot
        at this collection time. Polling faster than the agent collects is
        therefore harmless rather than a source of duplicate rows.
        """
        record = self._to_record(snapshot)
        try:
            with get_session() as session:
                session.add(record)
        except IntegrityError:
            return None

        return self._hydrate(record)

    def latest(self, host_name=None):
        """Most recent snapshot overall, or for one host."""
        statement = select(SnapshotRecord)

        if host_name is not None:
            statement = statement.where(SnapshotRecord.host_name == host_name)

        statement = self._ordered(statement).limit(1)

        with get_session() as session:
            record = session.execute(statement).scalars().first()

        return self._hydrate(record)

    def query(self, host_name=None, since=None, until=None, limit=DEFAULT_LIMIT, offset=0):
        """Snapshots newest first, filtered by host and collection time."""
        statement = self._filtered(select(SnapshotRecord), host_name, since, until)
        statement = self._ordered(statement).limit(limit).offset(offset)

        with get_session() as session:
            records = session.execute(statement).scalars().all()

        return [self._hydrate(record) for record in records]

    def count(self, host_name=None, since=None, until=None):
        """How many snapshots match, ignoring paging."""
        statement = self._filtered(
            select(func.count()).select_from(SnapshotRecord),
            host_name,
            since,
            until,
        )

        with get_session() as session:
            return session.execute(statement).scalar_one()

    def hosts(self):
        """Every host that has reported, most recently active first.

        Lets the dashboard populate a host selector without paging the whole
        table to discover which hosts exist.
        """
        last_collected_at = func.max(SnapshotRecord.collected_at)

        statement = (
            select(
                SnapshotRecord.host_name,
                last_collected_at,
                func.count(SnapshotRecord.id),
            )
            .group_by(SnapshotRecord.host_name)
            .order_by(last_collected_at.desc(), SnapshotRecord.host_name)
        )

        with get_session() as session:
            rows = session.execute(statement).all()

        return [
            HostSummary(
                host_name=host_name,
                # Aggregates bypass _hydrate(), so the UTC re-tagging that
                # callers rely on has to happen here too.
                last_collected_at=from_storage_time(collected_at),
                snapshot_count=snapshot_count,
            )
            for host_name, collected_at, snapshot_count in rows
        ]

    def prune(self, older_than):
        """Delete snapshots collected before the cutoff. Returns rows removed."""
        statement = delete(SnapshotRecord).where(
            SnapshotRecord.collected_at < to_storage_time(older_than)
        )

        with get_session() as session:
            return session.execute(statement).rowcount

    def _filtered(self, statement, host_name, since, until):
        # Shared by query() and count() so a page and its total can never be
        # computed from different filters.
        if host_name is not None:
            statement = statement.where(SnapshotRecord.host_name == host_name)
        if since is not None:
            statement = statement.where(SnapshotRecord.collected_at >= to_storage_time(since))
        if until is not None:
            statement = statement.where(SnapshotRecord.collected_at <= to_storage_time(until))

        return statement

    def _ordered(self, statement):
        # id breaks ties so paging stays stable if two snapshots share a time.
        return statement.order_by(
            SnapshotRecord.collected_at.desc(),
            SnapshotRecord.id.desc(),
        )

    def _to_record(self, snapshot):
        return SnapshotRecord(
            host_name=snapshot.systemInfo.hostName,
            collected_at=to_storage_time(snapshot.collectedAt),
            cpu_core_count=snapshot.cpuInfo.coreCount,
            cpu_usage_percent=snapshot.cpuInfo.usagePercent,
            mem_total_mb=snapshot.memoryInfo.totalMB,
            mem_used_mb=snapshot.memoryInfo.usedMB,
            disk_total_gb=snapshot.diskInfo.totalGB,
            disk_free_gb=snapshot.diskInfo.freeGB,
            os_name=snapshot.systemInfo.name,
            os_version=snapshot.systemInfo.version,
        )

    def _hydrate(self, record):
        """Hand back UTC-aware times so callers never see a bare datetime.

        Safe to assign: the session is closed and expire_on_commit is off, so
        the instance is detached and nothing is flushed back.
        """
        if record is None:
            return None

        record.collected_at = from_storage_time(record.collected_at)
        return record
