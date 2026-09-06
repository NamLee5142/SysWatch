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


class CompositeNotifier(Notifier):
    """Deliver to several places, and let each fail on its own.

    Isolated per notifier rather than per delivery: a mail server that is down
    must not cost the log line as well. Without this, the engine's single
    try/except would mean the first transport to raise silences every one
    after it, and which ones those are would depend on list order.
    """

    def __init__(self, notifiers):
        self._notifiers = list(notifiers)

    def __repr__(self):
        return f"CompositeNotifier({self._notifiers!r})"

    def deliver(self, change, alert):
        for notifier in self._notifiers:
            try:
                notifier.deliver(change, alert)
            except Exception:
                logger.warning(
                    "Could not deliver an alert through %s",
                    type(notifier).__name__,
                    exc_info=True,
                )


def build_notifier(settings):
    """The notifier the application uses, assembled from configuration.

    The log notifier is always present: it costs nothing, and it means a
    machine with no mail server still has a record of what fired somewhere an
    operator already looks. Everything else is off until configured.
    """
    notifiers = [LoggingNotifier()]

    if settings.smtp_host:
        # Imported here rather than at module scope so that the module holding
        # the password is not imported into every process that touches alerts.
        from app.alerts.smtp import SmtpNotifier

        notifiers.append(
            SmtpNotifier(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                sender=settings.smtp_from,
                recipients=settings.smtp_to,
            )
        )

    if settings.webhook_url:
        from app.alerts.webhook import WebhookNotifier

        notifiers.append(WebhookNotifier(url=settings.webhook_url))

    return CompositeNotifier(notifiers)

