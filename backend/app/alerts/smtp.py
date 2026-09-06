"""Sending an alert state change as mail.

There is deliberately no logger in this module.

`app/auth/` has none for the same reason: the surest way a secret never reaches
a log is that nothing in the file can write one. The password lives here, and
so does the code most likely to fail in a way somebody would want to log, which
is exactly the combination that leaks credentials. Failures propagate to
AlertEngine._announce, which logs them without ever having held the password.

The same care applies to `repr`: a dataclass or an f-string of `self` would put
the password in a traceback frame, an error message, or somebody's REPL.
"""
import smtplib
from email.message import EmailMessage

from app.alerts.notifier import OPENED, Notifier

# Bounded, because deliver() runs on the poller's thread: the engine evaluates,
# announces, and only then returns to collecting. A mail server that accepts a
# connection and then stops talking would otherwise stall collection
# indefinitely. Ten seconds is long enough for a slow relay and short enough
# that one missed poll is the whole cost.
#
# State changes are rare - a rule that fires and clears once an hour costs two
# of these - so the poll path is not paying this on every tick. If that ever
# stops being true, delivery belongs on its own thread rather than on a longer
# timeout.
TIMEOUT_SECONDS = 10


class SmtpNotifier(Notifier):
    """Mail one message per alert state change."""

    def __init__(
        self,
        *,
        host,
        port=587,
        username="",
        password="",
        sender="",
        recipients=(),
        timeout=TIMEOUT_SECONDS,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._recipients = list(recipients)
        self._timeout = timeout

    def __repr__(self):
        # Explicit, because the default would print every attribute including
        # the password.
        return f"SmtpNotifier(host={self._host!r}, port={self._port!r})"

    def deliver(self, change, alert):
        message = self._compose(change, alert)

        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as server:
            server.ehlo()

            if server.has_extn("starttls"):
                server.starttls()
                # Re-introduce: the server's advertised capabilities can differ
                # once the connection is encrypted, and the RFC requires it.
                server.ehlo()
            elif self._username:
                # Refusing is the point. A server that will not encrypt is a
                # server this password would cross in clear, and "the alert did
                # not arrive" is a far better outcome than "the mailbox
                # password is now on the network".
                raise RuntimeError(
                    f"{self._host} does not offer STARTTLS and credentials are "
                    "configured; refusing to send the password in clear"
                )

            if self._username:
                server.login(self._username, self._password)

            server.send_message(message)

    def _compose(self, change, alert):
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = ", ".join(self._recipients)

        # Severity first, so a mail client's subject column sorts and filters on
        # the thing that decides whether to get out of bed. "resolved" replaces
        # it on a recovery: the severity of an alert that has ended is not what
        # the reader needs to know.
        label = alert.severity if change == OPENED else "resolved"
        message["Subject"] = f"[{label}] {alert.rule_name} on {alert.host_name}"

        message.set_content(self._body(change, alert))
        return message

    def _body(self, change, alert):
        lines = [
            f"Alert {change}: {alert.rule_name}",
            "",
            f"Host:      {alert.host_name}",
            f"Metric:    {alert.metric}",
            f"Value:     {alert.value}",
            f"Threshold: {alert.operator} {alert.threshold}",
            f"Severity:  {alert.severity}",
            f"Started:   {alert.triggered_at}",
        ]

        if change != OPENED:
            lines.append(f"Resolved:  {alert.resolved_at}")

        return "\n".join(lines) + "\n"
