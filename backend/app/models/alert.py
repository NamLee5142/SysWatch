from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.models.snapshot import Metric

# Lowercase string literals, spelled the way `agent` states are in
# app/models/status.py. The order here (info < warning < critical) is only for
# sorting the alerts list; no logic branches on severity.
Severity = Literal["info", "warning", "critical"]

# Two states, on purpose. `acknowledged` / `silenced` belong with notification
# delivery, which this sprint does not build — see docs/sprint-8.md.
AlertState = Literal["ok", "firing"]

# Comparison direction for the threshold. Equality on a float metric is not
# useful, so `eq` is left out.
Operator = Literal["gt", "gte", "lt", "lte"]

# Trimmed and non-empty: a rule named "" or "   " is a UI slip, not a policy, and
# it should fail at POST rather than become a row the list renders blank.
RuleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]

# Reject nan and inf. Either would make a rule that silently never fires (or
# always fires), and there is no clean way to round-trip them through SQLite.
Threshold = Annotated[float, Field(allow_inf_nan=False)]


class AlertRuleCreate(BaseModel):
    """Body for POST /alert-rules."""

    name: RuleName
    metric: Metric
    operator: Operator
    threshold: Threshold
    severity: Severity = "warning"
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    """Body for PUT /alert-rules/{id}.

    Every field is optional and at least one is required — partial rather than
    full-replacement so a caller can flip `enabled` without re-sending the whole
    rule. The route applies only the fields actually sent (`exclude_unset`).
    """

    name: Optional[RuleName] = None
    metric: Optional[Metric] = None
    operator: Optional[Operator] = None
    threshold: Optional[Threshold] = None
    severity: Optional[Severity] = None
    enabled: Optional[bool] = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        return self


class AlertRule(BaseModel):
    """A configured threshold, as the API returns it."""

    id: int
    name: str
    metric: Metric
    operator: Operator
    threshold: float
    severity: Severity
    enabled: bool
    createdAt: datetime
    updatedAt: datetime

    @classmethod
    def from_record(cls, record) -> "AlertRule":
        """Build from an AlertRuleRecord.

        Taken structurally rather than by import, so the API models stay
        independent of the database layer — the rule Snapshot and Host follow.
        """
        return cls(
            id=record.id,
            name=record.name,
            metric=record.metric,
            operator=record.operator,
            threshold=record.threshold,
            severity=record.severity,
            enabled=record.enabled,
            createdAt=record.created_at,
            updatedAt=record.updated_at,
        )


class AlertRuleList(BaseModel):
    """Every configured rule."""

    items: list[AlertRule]


class Alert(BaseModel):
    """One alert occurrence — currently open (`firing`) or historical (`ok`).

    The rule's identity is copied onto the alert when it opens, so history stays
    truthful after the rule is edited or deleted: `ruleId` goes null on delete,
    but the copied `ruleName` / `metric` / `operator` / `threshold` / `severity`
    keep describing the condition that actually fired.
    """

    id: int
    ruleId: Optional[int]
    ruleName: str
    metric: Metric
    operator: Operator
    threshold: float
    severity: Severity
    hostName: str
    state: AlertState
    value: float
    triggeredAt: datetime
    resolvedAt: Optional[datetime]
    acknowledgedAt: Optional[datetime] = None
    acknowledgedBy: Optional[str] = None
    lastSeenAt: datetime

    @classmethod
    def from_record(cls, record) -> "Alert":
        return cls(
            id=record.id,
            ruleId=record.rule_id,
            ruleName=record.rule_name,
            metric=record.metric,
            operator=record.operator,
            threshold=record.threshold,
            severity=record.severity,
            hostName=record.host_name,
            state=record.state,
            value=record.value,
            triggeredAt=record.triggered_at,
            resolvedAt=record.resolved_at,
            acknowledgedAt=record.acknowledged_at,
            acknowledgedBy=record.acknowledged_by,
            lastSeenAt=record.last_seen_at,
        )


class AlertPage(BaseModel):
    """A page of alert history, newest first."""

    items: list[Alert]
    # Total rows matching the filters, ignoring limit and offset, so a caller
    # holding one page can tell whether more exist — as SnapshotPage does.
    count: int


class AlertList(BaseModel):
    """Active alerts — a plain list, like HostList; there are never many."""

    items: list[Alert]
