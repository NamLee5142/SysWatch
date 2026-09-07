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

    @property
    def name(self):
        """What to call this in a log line about a failure.

        A wrapper delegates, so an operator reading "could not deliver through
        SeverityFilter" instead of "through SmtpNotifier" - which is what they
        got before this existed - learns which transport is actually down.
        """
        return type(self).__name__

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
                    notifier.name,
                    exc_info=True,
                )


class NotificationMisconfigured(Exception):
    """Configuration that would deliver nothing, or deliver it nowhere."""


# Ordered, because "at least this severity" needs an order and a Literal has
# none. The names match app.alerts.evaluator.Severity.
SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


class SeverityFilter(Notifier):
    """Pass through only alerts at or above a severity.

    Wraps a transport rather than sitting in the engine, so the log notifier is
    unaffected: an operator who does not want to be mailed about warnings still
    wants warnings in the record. Filtering in the engine would lose them
    everywhere at once.

    The filter reads the alert's severity for both openings and resolutions. A
    resolution that got through while its opening did not would be a message
    about an incident the reader was never told had started.
    """

    def __init__(self, notifier, minimum):
        self._notifier = notifier
        self._minimum = SEVERITY_ORDER[minimum]

    @property
    def name(self):
        # The transport, not this wrapper. A filter never fails.
        return self._notifier.name

    def __repr__(self):
        return f"SeverityFilter({self._notifier!r})"

    def deliver(self, change, alert):
        if SEVERITY_ORDER.get(alert.severity, 0) < self._minimum:
            return

        self._notifier.deliver(change, alert)


def verify_notification_configuration(settings):
    """Refuse a configuration that cannot deliver, and say what is missing.

    Called at startup beside verify_security_configuration. A half-configured
    transport is not a security problem, but it fails the same way and should
    be found at the same moment: the alternative is discovering it when the
    first alert does not arrive, which is the worst time to learn anything.

    Returns a list of warnings worth logging.
    """
    warnings = []

    smtp_fields = {
        "SYSWATCH_SMTP_HOST": settings.smtp_host,
        "SYSWATCH_SMTP_FROM": settings.smtp_from,
        "SYSWATCH_SMTP_TO": settings.smtp_to,
    }
    configured = [name for name, value in smtp_fields.items() if value]

    if configured and len(configured) != len(smtp_fields):
        missing = [name for name, value in smtp_fields.items() if not value]
        raise NotificationMisconfigured(
            f"Mail is half configured: {', '.join(configured)} set, "
            f"{', '.join(missing)} missing. Set the rest, or unset all of them."
        )

    # A username with no password authenticates as nobody; a password with no
    # username is a secret sitting in a file for no reason.
    if bool(settings.smtp_username) != bool(settings.smtp_password):
        raise NotificationMisconfigured(
            "SYSWATCH_SMTP_USERNAME and SYSWATCH_SMTP_PASSWORD must be set "
            "together, or neither."
        )

    if settings.webhook_url and not settings.webhook_url.startswith(
        ("http://", "https://")
    ):
        # Never quoted back. A webhook URL is usually a credential, and this
        # message reaches the log.
        raise NotificationMisconfigured(
            "SYSWATCH_WEBHOOK_URL is not an http:// or https:// URL."
        )

    if settings.webhook_url and settings.webhook_url.startswith("http://"):
        warnings.append(
            "SYSWATCH_WEBHOOK_URL is http://: alert contents, and the token in "
            "the URL if it has one, cross the network in clear."
        )

    if not settings.smtp_host and not settings.webhook_url:
        warnings.append(
            "No alert transport is configured: alerts are recorded and logged, "
            "and nobody is told."
        )

    return warnings


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
            _filtered(settings, SmtpNotifier(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                sender=settings.smtp_from,
                recipients=settings.smtp_to,
            ))
        )

    if settings.webhook_url:
        from app.alerts.webhook import WebhookNotifier

        notifiers.append(_filtered(settings, WebhookNotifier(url=settings.webhook_url)))

    return CompositeNotifier(notifiers)


def _filtered(settings, notifier):
    """Outbound transports honour the minimum severity; the log does not."""
    return SeverityFilter(notifier, settings.notify_min_severity)
