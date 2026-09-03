"""seed default alert rules

Revision ID: 0a33e83916fa
Revises: c6a63f3f08c6
Create Date: 2026-09-02 17:19:51.139456

A data migration, not a schema one: a fresh database would otherwise have no
rules, the engine would evaluate nothing, and the feature would look broken on
first run. Seeding here rather than at app startup means a rule the user later
deletes stays deleted.
"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a33e83916fa'
down_revision: Union[str, Sequence[str], None] = 'c6a63f3f08c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# name is the key: the upgrade skips any that already exist, the downgrade
# removes exactly these. `disk` is used-percent (see the evaluator), so "almost
# full" is gt 90. The network threshold is a deliberately high placeholder —
# ~100 MiB/s sustained receive — for the user to tune.
DEFAULT_RULES = [
    {"name": "CPU usage high", "metric": "cpu", "operator": "gt", "threshold": 90.0, "severity": "warning"},
    {"name": "CPU usage critical", "metric": "cpu", "operator": "gt", "threshold": 95.0, "severity": "critical"},
    {"name": "Memory usage high", "metric": "memory", "operator": "gt", "threshold": 90.0, "severity": "warning"},
    {"name": "Disk almost full", "metric": "disk", "operator": "gt", "threshold": 90.0, "severity": "warning"},
    {"name": "Process count high", "metric": "processes", "operator": "gt", "threshold": 500.0, "severity": "info"},
    {"name": "Network receive rate high", "metric": "net_recv", "operator": "gt", "threshold": 104857600.0, "severity": "info"},
]

alert_rules = sa.table(
    "alert_rules",
    sa.column("name", sa.String),
    sa.column("metric", sa.String),
    sa.column("operator", sa.String),
    sa.column("threshold", sa.Float),
    sa.column("severity", sa.String),
    sa.column("enabled", sa.Boolean),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
)


def upgrade() -> None:
    """Insert the starter rules that are not already present."""
    connection = op.get_bind()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    existing = set(connection.execute(sa.select(alert_rules.c.name)).scalars())
    rows = [
        {**rule, "enabled": True, "created_at": now, "updated_at": now}
        for rule in DEFAULT_RULES
        if rule["name"] not in existing
    ]

    if rows:
        op.bulk_insert(alert_rules, rows)


def downgrade() -> None:
    """Remove exactly the seeded rules, by name."""
    names = [rule["name"] for rule in DEFAULT_RULES]
    op.execute(sa.delete(alert_rules).where(alert_rules.c.name.in_(names)))
