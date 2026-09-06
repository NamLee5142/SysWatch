"""Stand-ins for the alert stores, shared by the tests that drive the engine.

Shaped like what the real stores return, which is the SQLAlchemy record rather
than the API's Alert model - the store hydrates timestamps in place and hands
the record back. A fake with the API's camelCase names would pass every test
here and fail against the real thing.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.snapshot import Snapshot

BASE_TIME = datetime(2026, 8, 12, 11, 15, 27, tzinfo=timezone.utc)


def make_snapshot(cpu_usage=10.0, mem_used=4096, host_name="devbox", collected_at=BASE_TIME):
    return Snapshot.from_payload(
        {
            "collectedAt": collected_at.isoformat(),
            "cpuInfo": {"coreCount": 8, "usagePercent": cpu_usage},
            "memoryInfo": {"totalMB": 16384, "usedMB": mem_used},
            "diskInfo": {"totalGB": 512, "freeGB": 120},
            "systemInfo": {"name": "Windows", "version": "11", "hostName": host_name},
        }
    )


def rule(id, metric="cpu", operator="gt", threshold=90.0, severity="warning",
         name=None, enabled=True, silenced_until=None):
    return SimpleNamespace(
        id=id,
        silenced_until=silenced_until,
        name=name or f"rule-{id}",
        metric=metric,
        operator=operator,
        threshold=threshold,
        severity=severity,
        enabled=enabled,
    )


class FakeRuleStore:
    def __init__(self, *rules):
        self.rules = list(rules)

    def enabled_rules(self):
        return [r for r in self.rules if r.enabled]


class FakeAlertStore:
    """In-memory stand-in for AlertStore, enforcing the same invariant."""

    def __init__(self):
        self.rows = []
        self._next_id = 1

    def active(self, host_name):
        return [r for r in self.rows if r.host_name == host_name and r.state == "firing"]

    def open_new(self, *, rule, host_name, value, at):
        row = SimpleNamespace(
            id=self._next_id,
            rule_id=rule.id,
            rule_name=rule.name,
            metric=rule.metric,
            operator=rule.operator,
            threshold=rule.threshold,
            severity=rule.severity,
            host_name=host_name,
            state="firing",
            value=value,
            triggered_at=at,
            resolved_at=None,
            last_seen_at=at,
            acknowledged_at=None,
            acknowledged_by=None,
            last_notified_at=None,
        )
        self._next_id += 1
        self.rows.append(row)
        return row

    def touch(self, *, alert_id, value, at):
        row = self._by_id(alert_id)
        row.value = value
        row.last_seen_at = at

    def resolve(self, *, alert_id, value, at):
        row = self._by_id(alert_id)
        row.state = "ok"
        row.value = value
        row.resolved_at = at
        row.last_seen_at = at
        # Returned, like AlertStore.resolve returns the closed alert. A caller
        # announcing the resolution needs the resolved row; the one it was
        # holding still says the alert is firing.
        return row

    def acknowledge(self, *, alert_id, username, at=None):
        row = self._by_id(alert_id)
        if row.acknowledged_at is None:
            row.acknowledged_at = at
            row.acknowledged_by = username
        return row

    def get(self, alert_id):
        return next((r for r in self.rows if r.id == alert_id), None)

    def mark_notified(self, *, alert_id, at):
        self._by_id(alert_id).last_notified_at = at

    def _by_id(self, alert_id):
        return next(r for r in self.rows if r.id == alert_id)
