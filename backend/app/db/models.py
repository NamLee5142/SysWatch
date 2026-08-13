from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, MetaData, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit names for every constraint and index. SQLite cannot ALTER a
# constraint it cannot name, so Alembic needs these to migrate the schema later.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class SnapshotRecord(Base):
    """One collected snapshot, flattened from the agent's nested payload."""

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    host_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Stamped by the agent at collection time, not by the backend at poll time.
    # SQLite stores no offset, so values must be normalised to UTC before write.
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    cpu_core_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cpu_usage_percent: Mapped[float] = mapped_column(Float, nullable=False)

    mem_total_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    mem_used_mb: Mapped[int] = mapped_column(Integer, nullable=False)

    disk_total_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    disk_free_gb: Mapped[int] = mapped_column(Integer, nullable=False)

    # Denormalised rather than held in a hosts table: a machine's OS version
    # genuinely changes over time, so it is a property of the snapshot.
    os_name: Mapped[str] = mapped_column(String(255), nullable=False)
    os_version: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        # Makes the poller idempotent: re-reading the agent's latest snapshot
        # cannot insert a duplicate row. Also provides the index that serves
        # host-scoped history queries.
        UniqueConstraint("host_name", "collected_at"),
        # Serves cross-host time queries and retention pruning, which filter on
        # collected_at alone and cannot use the host-leading index above.
        Index("ix_snapshots_collected_at", "collected_at"),
    )

    def __repr__(self):
        return (
            f"SnapshotRecord(id={self.id!r}, host_name={self.host_name!r}, "
            f"collected_at={self.collected_at!r})"
        )
