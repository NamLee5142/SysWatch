from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import session as db_session
from app.db.models import Base, SnapshotRecord


@pytest.fixture
def session():
    # A plain Session rather than app.db.get_session(): several tests provoke an
    # IntegrityError on purpose, and get_session() commits on exit, which would
    # fail on the already-rolled-back transaction.
    db_session.dispose_engine()
    engine = db_session.init_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as active:
        yield active
        active.rollback()

    db_session.dispose_engine()


def make_record(host_name="devbox", collected_at=None):
    return SnapshotRecord(
        host_name=host_name,
        collected_at=collected_at or datetime(2026, 8, 12, 11, 15, 27, tzinfo=timezone.utc),
        cpu_core_count=20,
        cpu_usage_percent=42.5,
        mem_total_mb=16124,
        mem_used_mb=12009,
        disk_total_gb=475,
        disk_free_gb=37,
        os_name="Microsoft Windows",
        os_version="10.0.26200",
    )


def test_record_round_trips(session):
    session.add(make_record())
    session.flush()

    stored = session.execute(select(SnapshotRecord)).scalar_one()
    assert stored.host_name == "devbox"
    assert stored.cpu_core_count == 20
    assert stored.cpu_usage_percent == 42.5
    assert stored.os_version == "10.0.26200"


def test_duplicate_host_and_time_is_rejected(session):
    session.add(make_record())
    session.flush()

    session.add(make_record())
    with pytest.raises(IntegrityError):
        session.flush()


def test_same_time_on_a_different_host_is_allowed(session):
    session.add(make_record(host_name="devbox"))
    session.add(make_record(host_name="buildbox"))
    session.flush()

    assert len(session.execute(select(SnapshotRecord)).scalars().all()) == 2


def test_required_columns_reject_null(session):
    record = make_record()
    record.cpu_usage_percent = None
    session.add(record)

    with pytest.raises(IntegrityError):
        session.flush()


def test_collected_at_reads_back_without_a_timezone(session):
    session.add(make_record())
    session.flush()
    session.expire_all()

    stored = session.execute(select(SnapshotRecord)).scalar_one()

    # SQLite has no timezone type, so the offset written is not returned. Values
    # must be normalised to UTC on write and re-tagged as UTC on read.
    assert stored.collected_at.tzinfo is None
    assert stored.collected_at == datetime(2026, 8, 12, 11, 15, 27)


def test_schema_has_expected_indexes(session):
    inspector = inspect(session.get_bind())

    indexes = {index["name"] for index in inspector.get_indexes("snapshots")}
    assert "ix_snapshots_collected_at" in indexes

    # Named by the metadata naming convention, which Alembic needs in order to
    # alter the constraint on SQLite later.
    unique = {
        constraint["name"]: constraint["column_names"]
        for constraint in inspector.get_unique_constraints("snapshots")
    }
    assert unique == {"uq_snapshots_host_name_collected_at": ["host_name", "collected_at"]}


def test_table_has_expected_columns(session):
    inspector = inspect(session.get_bind())

    columns = {column["name"] for column in inspector.get_columns("snapshots")}
    assert columns == {
        "id",
        "host_name",
        "collected_at",
        "cpu_core_count",
        "cpu_usage_percent",
        "mem_total_mb",
        "mem_used_mb",
        "disk_total_gb",
        "disk_free_gb",
        "os_name",
        "os_version",
        "process_count",
        "net_bytes_sent_per_sec",
        "net_bytes_recv_per_sec",
        "process_top",
        "network_interfaces",
    }
