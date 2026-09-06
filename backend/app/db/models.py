from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    MetaData,
    String,
    UniqueConstraint,
)
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

    # Process and network metrics, all nullable: rows written before Sprint 7
    # have none, and an agent built before it sends none. The three scalars are
    # aggregates that /snapshots/series can bucket; the two JSON columns are
    # point-in-time detail, read only from the latest row.
    process_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    net_bytes_sent_per_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_bytes_recv_per_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    process_top: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    network_interfaces: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

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


class AlertRuleRecord(Base):
    """A configurable threshold. Alert policy lives here, never in the agent."""

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # One of app.models.snapshot.Metric; the operator is one of
    # app.models.alert.Operator. Stored as plain text so a new metric or
    # operator does not need a schema change.
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    operator: Mapped[str] = mapped_column(String(16), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Naive UTC, stamped by AlertRuleStore on write — the same convention
    # collected_at follows. No server default, so the column never disagrees
    # with the repository's timezone handling.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self):
        return (
            f"AlertRuleRecord(id={self.id!r}, name={self.name!r}, "
            f"metric={self.metric!r}, operator={self.operator!r}, "
            f"threshold={self.threshold!r}, enabled={self.enabled!r})"
        )


class AlertRecord(Base):
    """One alert occurrence — currently firing, or resolved history.

    The rule's identity is copied in when the alert opens (`rule_name` through
    `severity`), so a past alert still describes the condition that fired after
    the rule is edited or deleted. `rule_id` goes NULL on delete; the copies do
    not.
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    rule_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True
    )
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    operator: Mapped[str] = mapped_column(String(16), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)

    host_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'firing' or 'ok' — app.models.alert.AlertState.
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    # Most recent evaluated metric value, in the metric's own unit.
    value: Mapped[float] = mapped_column(Float, nullable=False)

    # All naive UTC, stamped from the snapshot's collectedAt by the engine.
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Acknowledgement: somebody has seen this and is dealing with it.
    #
    # Columns on the alert rather than a table of their own. It is an attribute
    # of the one alert - who, and when - and a join would buy nothing but a
    # second thing to keep in step when an alert is deleted.
    #
    # The username is copied, not a foreign key to users.id. An alert is
    # history, and history should stay readable after the account that made it
    # is deleted - the same reason rule_name is copied onto the alert rather
    # than joined from alert_rules.
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        # The "open alert for this host" lookup the engine runs every tick, and
        # the filter behind GET /alerts/active.
        Index("ix_alerts_host_name_state", "host_name", "state"),
        # Resolving a rule's alerts when it is disabled or deleted.
        Index("ix_alerts_rule_id", "rule_id"),
        # GET /alerts history, newest first.
        Index("ix_alerts_triggered_at", "triggered_at"),
    )

    def __repr__(self):
        return (
            f"AlertRecord(id={self.id!r}, rule_id={self.rule_id!r}, "
            f"host_name={self.host_name!r}, state={self.state!r}, "
            f"value={self.value!r})"
        )


class UserRecord(Base):
    """An account that can log in to the backend.

    The agent knows nothing about these: authentication lives at the backend
    boundary, which is the whole reason the agent stays on loopback.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Unique so two accounts cannot answer to the same login, and indexed
    # because every login looks a user up by exactly this.
    username: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    # Argon2id, produced by app/auth/password.py. Never selected into an API
    # model — CurrentUser has no field it could land in.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'admin' or 'viewer' — app.models.auth.Role. Text, so adding a role later
    # is not a schema change.
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    # Checked on every authenticated request, not just at login: disabling an
    # account has to end the sessions it already holds.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Naive UTC, stamped by the store — the convention collected_at follows.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self):
        # Deliberately no password_hash, so a stray repr in a log or traceback
        # cannot carry one.
        return (
            f"UserRecord(id={self.id!r}, username={self.username!r}, "
            f"role={self.role!r}, enabled={self.enabled!r})"
        )


class SessionRecord(Base):
    """One logged-in browser.

    The raw session token is never stored. It exists in the cookie and nowhere
    else; this row holds only an HMAC of it, so a reader of the database cannot
    mint a cookie that impersonates anyone.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # HMAC-SHA256(SESSION_SECRET, raw_token), hex. Unique because it is the
    # lookup key for every authenticated request.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # CASCADE: deleting a user must not leave sessions that resolve to nobody.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Absolute, set at login. Activity updates last_seen_at but does not move
    # this — a session has a fixed lifetime rather than an extendable one.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # Ending every session a user holds, on logout-everywhere or on delete.
        Index("ix_sessions_user_id", "user_id"),
        # The expiry sweep, which filters on this column alone.
        Index("ix_sessions_expires_at", "expires_at"),
    )

    def __repr__(self):
        # No token_hash: it is not the token, but it is still the lookup key.
        return (
            f"SessionRecord(id={self.id!r}, user_id={self.user_id!r}, "
            f"expires_at={self.expires_at!r})"
        )
