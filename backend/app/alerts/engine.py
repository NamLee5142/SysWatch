import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.alerts.evaluator import evaluate as evaluate_rule
from app.alerts.notifier import OPENED, RESOLVED

logger = logging.getLogger(__name__)


@dataclass
class EvaluationSummary:
    """What one evaluate() pass did — enough for the poller's log line."""

    evaluated: int = 0
    opened: int = 0
    resolved: int = 0
    still_firing: int = 0
    reminded: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.opened or self.resolved)


class AlertEngine:
    """Turns one snapshot into alert state changes.

    The backend half of "the agent collects facts, the backend decides whether
    they constitute an alert". Holds no SQLAlchemy: it works entirely through a
    rule store and an alert store, so it is unit-testable against fakes and the
    persistence layer can change beneath it.
    """

    def __init__(self, rule_store, alert_store, notifier=None, repeat_after=None):
        self._rule_store = rule_store
        self._alert_store = alert_store
        self._notifier = notifier
        # A timedelta, or None for "say it once". None is the default because
        # deciding on somebody's behalf to mail them every four hours is not a
        # default anyone should get by accident.
        self._repeat_after = repeat_after

    def evaluate(self, snapshot, host_name=None) -> EvaluationSummary:
        """Evaluate every enabled rule against one snapshot and persist the result.

        One firing alert per (rule, host) at a time: a violation with no open
        alert opens one, a violation with an open alert updates it in place
        (no new row every tick), and a return to normal resolves it.

        host_name overrides the name inside the payload, for the same reason
        SnapshotStore.save takes one: on the ingestion path the payload is
        written by the machine being identified. Without it a pushed snapshot
        would be *stored* under the credential's host and *alerted* under
        whatever hostname it claimed - so one agent could open and resolve
        another machine's alerts while its own rows went elsewhere, which is a
        stranger failure than either half alone.

        The poller leaves it None: it fetched the snapshot from an agent it was
        configured to reach, so the two names are the same by construction.
        """
        host_name = host_name or snapshot.systemInfo.hostName
        # The alert is stamped with when the metrics were collected, not when
        # this ran — the same choice the snapshot row makes, and it keeps the
        # engine deterministic to test.
        at = snapshot.collectedAt

        summary = EvaluationSummary()

        rules = list(self._rule_store.enabled_rules())
        enabled_ids = {rule.id for rule in rules}

        # Silenced rules evaluate and record exactly as they always did. Only
        # the announcement is withheld, and only while the silence lasts - the
        # expiry is compared against now rather than against the snapshot's
        # collectedAt, because a silence is a decision somebody made about the
        # clock on the wall, not about when the metric was sampled.
        now = datetime.now(timezone.utc)
        silenced_ids = {
            rule.id
            for rule in rules
            if rule.silenced_until is not None and rule.silenced_until > now
        }

        open_alerts = list(self._alert_store.active(host_name))
        open_by_rule = {
            alert.rule_id: alert for alert in open_alerts if alert.rule_id is not None
        }

        for rule in rules:
            summary.evaluated += 1
            value, violated = evaluate_rule(rule, snapshot)
            existing = open_by_rule.get(rule.id)

            if violated:
                if existing is None:
                    opened = self._alert_store.open_new(
                        rule=rule, host_name=host_name, value=value, at=at
                    )
                    summary.opened += 1
                    if rule.id not in silenced_ids:
                        self._announce(OPENED, opened)
                else:
                    self._alert_store.touch(alert_id=existing.id, value=value, at=at)
                    summary.still_firing += 1

                    if rule.id not in silenced_ids and self._reminder_due(existing, now):
                        # Re-read: the row the loop is holding was fetched
                        # before touch(), so its value is one tick stale, and a
                        # reminder quoting a stale number invites the reader to
                        # distrust the next one.
                        current = self._alert_store.get(existing.id)
                        self._announce(OPENED, current)
                        summary.reminded += 1
            elif existing is not None and value is not None:
                # Enabled, evaluated, no longer breaching — recovered. A None
                # value (metric absent) is missing data, not a recovery, so it
                # falls through and the alert stays open.
                resolved = self._alert_store.resolve(
                    alert_id=existing.id, value=value, at=at
                )
                summary.resolved += 1
                if rule.id not in silenced_ids:
                    self._announce(RESOLVED, resolved)

        # A rule disabled or deleted since it last fired leaves a stuck alert
        # otherwise: its own evaluation never runs because enabled_rules() no
        # longer returns it. Resolve it here on the value it last held.
        for alert in open_alerts:
            if alert.rule_id not in enabled_ids:
                resolved = self._alert_store.resolve(
                    alert_id=alert.id, value=alert.value, at=at
                )
                summary.resolved += 1
                self._announce(RESOLVED, resolved)

        if summary.changed:
            logger.info(
                "Alerts for %s: %d opened, %d resolved",
                host_name,
                summary.opened,
                summary.resolved,
            )

        return summary

    def _reminder_due(self, alert, now):
        """Whether this still-firing alert has gone unmentioned long enough.

        Acknowledgement is what makes this stop. Everything else about an
        acknowledged alert is unchanged - it stays open, it stays on the
        dashboard, and its resolution is still announced - but the person who
        said "I am dealing with it" does not need telling again every four
        hours.
        """
        if self._repeat_after is None or alert.acknowledged_at is not None:
            return False

        # An alert opened before this feature existed has no last_notified_at.
        # Counting from when it was opened is the closest honest answer, and
        # keeps the first reminder a repeat interval away rather than instant.
        since = alert.last_notified_at or alert.triggered_at

        return since is not None and now - since >= self._repeat_after

    def _announce(self, change, alert):
        """Hand a state change to the notifier, and never fail because of it.

        The same rule persistence follows in SnapshotService: collecting and
        evaluating are the work, and telling somebody about it is a side
        effect. A mail server that is down must not stop alerts being recorded
        - the row is the durable thing, and the message is a courtesy on top
        of it.
        """
        if self._notifier is None or alert is None:
            return

        try:
            self._notifier.deliver(change, alert)
        except Exception:
            logger.warning("Could not deliver an alert notification", exc_info=True)

        # Stamped whether or not delivery worked. It records that this alert
        # has had its turn, and a transport that is down should not turn the
        # reminder into a retry loop hammering it every ten seconds.
        self._alert_store.mark_notified(
            alert_id=alert.id, at=datetime.now(timezone.utc)
        )
