from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.db import get_session
from app.db.models import SnapshotRecord

DEFAULT_LIMIT = 100

# strftime patterns that truncate a timestamp to the start of its bucket. The
# grouped-by value doubles as the bucket's label, so the two can never disagree.
BUCKET_FORMATS = {
    "minute": "%Y-%m-%d %H:%M:00",
    "hour": "%Y-%m-%d %H:00:00",
    "day": "%Y-%m-%d 00:00:00",
}
BUCKET_LABEL_FORMAT = "%Y-%m-%d %H:%M:%S"
RAW_BUCKET = "raw"


@dataclass(frozen=True)
class HostSummary:
    """One host's activity, aggregated over its snapshots.

    Not a SnapshotRecord: every field here is computed across many rows, so
    handing back an ORM instance would imply a row that does not exist.
    """

    host_name: str
    last_collected_at: datetime
    snapshot_count: int


@dataclass(frozen=True)
class SeriesPoint:
    """One plotted value: a bucket's start time and the average within it."""

    at: datetime
    value: float


def metric_expression(metric):
    """SQL for one metric's per-row value.

    cpu, memory and disk come back as a percentage on one 0-100 axis; processes
    and network come back in their own units (a count, bytes per second) — see
    METRIC_UNIT in app.models.snapshot.

    nullif() guards the divisions: SQLite would quietly return NULL on a zero
    total, but PostgreSQL raises, and this has to survive that move.
    """
    if metric == "cpu":
        return SnapshotRecord.cpu_usage_percent
    if metric == "memory":
        return 100.0 * SnapshotRecord.mem_used_mb / func.nullif(SnapshotRecord.mem_total_mb, 0)
    if metric == "disk":
        used_gb = SnapshotRecord.disk_total_gb - SnapshotRecord.disk_free_gb
        return 100.0 * used_gb / func.nullif(SnapshotRecord.disk_total_gb, 0)
    if metric == "processes":
        return SnapshotRecord.process_count
    if metric == "net_sent":
        return SnapshotRecord.net_bytes_sent_per_sec
    if metric == "net_recv":
        return SnapshotRecord.net_bytes_recv_per_sec

    raise ValueError(f"Unknown metric: {metric}")


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

    def series(self, metric, host_name=None, since=None, until=None,
               bucket="hour", limit=DEFAULT_LIMIT):
        """Bucketed averages for one metric, oldest first.

        Deliberately the opposite order to query(), which is newest-first for
        paging: a chart is read left to right through time. Returning at most
        `limit` points is what keeps a month of 10-second samples from being
        shipped to a browser to draw a few hundred pixels.
        """
        value = metric_expression(metric)

        if bucket == RAW_BUCKET:
            statement = self._filtered(
                select(SnapshotRecord.collected_at, value), host_name, since, until
            )
            # id breaks ties for the same reason paging needs it: two snapshots
            # can share a collection time.
            statement = statement.order_by(
                SnapshotRecord.collected_at.asc(), SnapshotRecord.id.asc()
            )
        else:
            label = func.strftime(self._bucket_format(bucket), SnapshotRecord.collected_at)
            statement = self._filtered(
                select(label, func.avg(value)), host_name, since, until
            )
            statement = statement.group_by(label).order_by(label.asc())

        with get_session() as session:
            rows = session.execute(statement.limit(limit)).all()

        return [
            SeriesPoint(at=self._point_time(at, bucket), value=float(value))
            for at, value in rows
            # A NULL value has nothing to plot: for cpu/memory/disk every row in
            # the bucket had a zero total, for processes/network none of them
            # carried the metric (a pre-Sprint-7 row, or an older agent).
            # Plotting a zero would misread as an idle machine.
            if value is not None
        ]

    def _bucket_format(self, bucket):
        try:
            return BUCKET_FORMATS[bucket]
        except KeyError:
            raise ValueError(f"Unknown bucket: {bucket}") from None

    def _point_time(self, at, bucket):
        # A raw point carries a real datetime column; a bucketed one carries the
        # strftime label, which is a string and has to be read back.
        if bucket == RAW_BUCKET:
            return from_storage_time(at)

        return datetime.strptime(at, BUCKET_LABEL_FORMAT).replace(tzinfo=timezone.utc)

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
        processes = snapshot.processInfo
        network = snapshot.networkInfo

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
            # Left NULL when the agent sent no block, so a pre-Sprint-7 agent
            # stores exactly what it did before.
            process_count=processes.count if processes is not None else None,
            process_top=(
                [entry.model_dump() for entry in processes.top]
                if processes is not None
                else None
            ),
            # The series endpoint charts one number per snapshot, so the
            # per-interface rates are summed to a machine total here.
            net_bytes_sent_per_sec=(
                sum(nic.bytesSentPerSec for nic in network.interfaces)
                if network is not None
                else None
            ),
            net_bytes_recv_per_sec=(
                sum(nic.bytesRecvPerSec for nic in network.interfaces)
                if network is not None
                else None
            ),
            network_interfaces=(
                [nic.model_dump() for nic in network.interfaces]
                if network is not None
                else None
            ),
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
