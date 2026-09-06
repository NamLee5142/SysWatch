"""Telling somebody that an alert changed state.

Sprint 8 built the evaluator and Sprint 10 made the whole thing deployable.
Between them an alert went no further than a database row: it was visible to
anyone already looking at the dashboard, which is the one audience alerting
does not need to reach.

A notifier is given state changes, not evaluations. A rule that has been
breached for six hours is one event, not two thousand - the interesting moments
are when it started and when it stopped, and anything that sends a message per
tick is a mail loop with extra steps.

The alert handed to `deliver` is the stored alert, as the alert store returns
it: the rule's identity is copied onto it when it opens, so a message stays
truthful about what fired even after the rule is edited or deleted. Turning it
into the JSON the API serves is a transport's job, not the engine's.
"""
import logging

logger = logging.getLogger(__name__)

# The two state changes worth a message. "still firing" is deliberately absent.
OPENED = "opened"
RESOLVED = "resolved"


class Notifier:
    """Somewhere an alert state change can be sent.

    Deliberately one method. Two transports do not need a plugin system, and a
    registry would be the speculative half of the design - implementations are
    wired explicitly where the engine is built.
    """

    def deliver(self, change, alert):
        """Send one state change. `change` is OPENED or RESOLVED."""
        raise NotImplementedError


class LoggingNotifier(Notifier):
    """Write the state change to the log.

    Not a placeholder. On a machine with no mail server and no webhook this is
    the delivery mechanism, and the log is somewhere an operator already looks
    - `syswatch.log` is rotated, kept, and named in the deployment guide.

    It also gives every later transport something to be compared against: a
    test can assert what would have been sent without standing up an SMTP
    server.
    """

    def deliver(self, change, alert):
        # WARNING for a new alert, INFO for a recovery. An operator grepping a
        # log for what went wrong wants the openings; the resolutions are
        # context. Both are at or above the default level, so neither is lost.
        report = logger.warning if change == OPENED else logger.info

        report(
            "Alert %s: %s on %s - %s is %s (%s %s), severity %s",
            change,
            alert.rule_name,
            alert.host_name,
            alert.metric,
            alert.value,
            alert.operator,
            alert.threshold,
            alert.severity,
        )
