"""Upgrade a database with a realistic amount of history in it.

The migration tests next door check that each revision does the right thing;
every one of them runs against a table holding a row or two. What an install
actually meets is a machine that has been collecting snapshots every few
seconds for months, and the failure mode there is not a wrong column — it is
`alembic upgrade head` sitting for minutes with the service down while somebody
wonders whether it has hung.

That cost is decided by whether alembic's batch mode recreates the table.
Recreating copies every row; a plain ALTER TABLE ADD COLUMN is a metadata
change SQLite does in constant time. Today the snapshots migration adds
nullable columns and so takes the cheap path, which is why an upgrade over
200,000 rows takes a tenth of a second. Add a NOT NULL column or change a
constraint and batch mode silently switches to recreate-and-copy, at which
point the same upgrade becomes proportional to how long the machine has been
monitored. test_the_upgrade_does_not_copy_the_table is there to make that
switch visible in review rather than during an install.
"""
import time
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from sqlalchemy import create_engine, inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# The Sprint 5 baseline: snapshots exist, nothing else does.
BASELINE_REVISION = "c69cb3ded3fd"
# The Sprint 8 head, one before authentication.
ALERT_SEED_REVISION = "0a33e83916fa"
# The last revision that is pure DDL, and so the last one alembic can render
# without a database to read from.
LAST_SCHEMA_REVISION = "c6a63f3f08c6"

# Enough to be a real table rather than a sketch, small enough that the suite
# does not pay for it. The behaviour it demonstrates is independent of the
# number; 200,000 was measured by hand and recorded in the README.
SNAPSHOT_ROWS = 5000

SNAPSHOT_COLUMNS = (
    "host_name, collected_at, cpu_core_count, cpu_usage_percent, mem_total_mb, "
    "mem_used_mb, disk_total_gb, disk_free_gb, os_name, os_version"
)


@pytest.fixture
def alembic_config(tmp_path, monkeypatch):
    database = (tmp_path / "scale.db").as_posix()
    monkeypatch.setenv("SYSWATCH_DATABASE_URL", f"sqlite:///{database}")
    return Config(str(BACKEND_ROOT / "alembic.ini")), database


def fill_snapshots(engine, count=SNAPSHOT_ROWS):
    """Insert `count` snapshots spread over several hosts and timestamps.

    The unique constraint is on (host_name, collected_at), so both vary.
    """
    rows = [
        {
            "host": f"host{index % 5}",
            "at": f"2026-01-01 {index // 3600 % 24:02d}:"
            f"{index // 60 % 60:02d}:{index % 60:02d}.{index:06d}",
            "cpu": float(index % 100),
        }
        for index in range(count)
    ]

    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO snapshots ({SNAPSHOT_COLUMNS}) VALUES "
                "(:host, :at, 8, :cpu, 16384, 4096, 512, 120, 'Windows', '11')"
            ),
            rows,
        )

    return rows


def scalar(engine, sql):
    with engine.connect() as connection:
        return connection.execute(text(sql)).scalar_one()


def test_every_row_survives_the_full_upgrade(alembic_config):
    config, database = alembic_config
    command.upgrade(config, BASELINE_REVISION)
    engine = create_engine(f"sqlite:///{database}")
    rows = fill_snapshots(engine)

    command.upgrade(config, "head")

    assert scalar(engine, "SELECT COUNT(*) FROM snapshots") == SNAPSHOT_ROWS

    # Not just the count: the values have to come through unchanged, and the
    # columns added along the way have to be NULL rather than defaulted.
    with engine.connect() as connection:
        first = connection.execute(
            text(
                "SELECT host_name, cpu_usage_percent, process_count, process_top "
                "FROM snapshots ORDER BY id LIMIT 1"
            )
        ).one()
        last = connection.execute(
            text(
                "SELECT host_name, cpu_usage_percent FROM snapshots "
                "ORDER BY id DESC LIMIT 1"
            )
        ).one()

    assert (first.host_name, first.cpu_usage_percent) == (rows[0]["host"], rows[0]["cpu"])
    assert (last.host_name, last.cpu_usage_percent) == (rows[-1]["host"], rows[-1]["cpu"])
    assert first.process_count is None
    assert first.process_top is None


def test_the_upgrade_does_not_copy_the_table():
    """The property that keeps the upgrade constant-time.

    Rendered offline, so this reads the SQL alembic would run rather than
    inferring it from how long a run took. A recreate shows up as a
    CREATE TABLE _alembic_tmp_snapshots and an INSERT INTO ... SELECT that
    copies every row; a metadata-only change shows up as ALTER TABLE ADD COLUMN.

    The range stops at the last schema revision. The one after it seeds default
    alert rules by reading the table first, and a read has nothing to return
    when no database is connected — offline mode can render DDL, not decisions
    made from data.
    """
    buffer = StringIO()
    config = Config(str(BACKEND_ROOT / "alembic.ini"), output_buffer=buffer)

    try:
        command.upgrade(config, f"{BASELINE_REVISION}:{LAST_SCHEMA_REVISION}", sql=True)
    except CommandError as error:
        # Batch mode cannot render a move-and-copy offline: it needs a live
        # connection to reflect the table it is about to rebuild. So this
        # failure *is* the finding, and says so rather than leaving alembic's
        # wording to be decoded.
        pytest.fail(
            "A migration now rebuilds a table instead of altering it, which "
            "makes the upgrade cost proportional to stored history. Time it "
            "against a realistic database and update the README before "
            f"shipping. alembic said: {error}"
        )

    statements = buffer.getvalue().upper()

    assert "ALTER TABLE SNAPSHOTS ADD COLUMN PROCESS_COUNT" in statements
    assert "_ALEMBIC_TMP_SNAPSHOTS" not in statements
    assert "INSERT INTO SNAPSHOTS SELECT" not in statements


def test_indexes_and_constraints_survive_at_scale(alembic_config):
    config, database = alembic_config
    command.upgrade(config, BASELINE_REVISION)
    engine = create_engine(f"sqlite:///{database}")
    fill_snapshots(engine)

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert [index["name"] for index in inspector.get_indexes("snapshots")] == [
        "ix_snapshots_collected_at"
    ]
    assert [u["name"] for u in inspector.get_unique_constraints("snapshots")] == [
        "uq_snapshots_host_name_collected_at"
    ]

    # An index that exists but is not used would be an index in name only.
    with engine.connect() as connection:
        plan = connection.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT * FROM snapshots "
                "WHERE collected_at > '2026-01-01' ORDER BY collected_at DESC LIMIT 50"
            )
        ).all()

    assert any("ix_snapshots_collected_at" in str(step) for step in plan)


def test_the_unique_constraint_still_rejects_duplicates_after_upgrading(alembic_config):
    config, database = alembic_config
    command.upgrade(config, BASELINE_REVISION)
    engine = create_engine(f"sqlite:///{database}")
    rows = fill_snapshots(engine, count=100)

    command.upgrade(config, "head")

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO snapshots ({SNAPSHOT_COLUMNS}) VALUES "
                    "(:host, :at, 8, 1.0, 16384, 4096, 512, 120, 'Windows', '11')"
                ),
                {"host": rows[0]["host"], "at": rows[0]["at"]},
            )


def test_alert_history_and_rules_survive_the_upgrade(alembic_config):
    """A database that has been raising alerts, not just storing snapshots."""
    config, database = alembic_config
    command.upgrade(config, ALERT_SEED_REVISION)
    engine = create_engine(f"sqlite:///{database}")
    fill_snapshots(engine, count=1000)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO alert_rules (name, metric, operator, threshold, "
                "severity, enabled, created_at, updated_at) VALUES "
                "('Mine', 'cpu', 'gt', 99, 'warning', 1, '2026-01-01', '2026-01-01')"
            )
        )
        rule_id = connection.execute(
            text("SELECT id FROM alert_rules WHERE name = 'Mine'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO alerts (rule_id, rule_name, metric, operator, threshold, "
                "severity, host_name, state, value, triggered_at, last_seen_at) VALUES "
                "(:rule, 'Mine', 'cpu', 'gt', 99, 'warning', 'devbox', 'resolved', "
                "99.5, :at, :at)"
            ),
            [
                {"rule": rule_id, "at": f"2026-01-0{n % 9 + 1} 12:00:{n % 60:02d}.{n:04d}"}
                for n in range(500)
            ],
        )

    command.upgrade(config, "head")

    assert scalar(engine, "SELECT COUNT(*) FROM snapshots") == 1000
    assert scalar(engine, "SELECT COUNT(*) FROM alerts") == 500
    # The six seeded rules plus the operator's own, not seeded twice.
    assert scalar(engine, "SELECT COUNT(*) FROM alert_rules") == 7
    assert scalar(engine, "SELECT COUNT(*) FROM users") == 0


def test_the_database_lands_at_head(alembic_config):
    config, database = alembic_config
    command.upgrade(config, BASELINE_REVISION)
    engine = create_engine(f"sqlite:///{database}")
    fill_snapshots(engine)

    command.upgrade(config, "head")

    from alembic.script import ScriptDirectory

    expected = ScriptDirectory.from_config(config).get_current_head()
    assert scalar(engine, "SELECT version_num FROM alembic_version") == expected


def test_the_upgrade_finishes_quickly_enough_to_run_during_an_install(alembic_config):
    """A ceiling, not a benchmark.

    The measured cost is hundredths of a second, so this passes with four
    orders of magnitude to spare on any machine. It is here to fail loudly if a
    future revision makes the upgrade proportional to stored history — at which
    point the number below is the one to argue with.
    """
    config, database = alembic_config
    command.upgrade(config, BASELINE_REVISION)
    engine = create_engine(f"sqlite:///{database}")
    fill_snapshots(engine)
    engine.dispose()

    started = time.perf_counter()
    command.upgrade(config, "head")
    elapsed = time.perf_counter() - started

    assert elapsed < 30, f"upgrade of {SNAPSHOT_ROWS} rows took {elapsed:.2f}s"
