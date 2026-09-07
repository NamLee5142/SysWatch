"""Posting an alert state change to an HTTP endpoint.

Like app/alerts/smtp.py, this module has no logger.

That is less obvious here than it is for a password, so it is worth stating: a
webhook URL is usually itself a credential. Slack, Discord and Teams all embed
a secret token in the path, and anyone holding the URL can post as you. It is
configuration that looks like an address and behaves like a key.

So the URL is never logged, never in a `repr`, and - the easy one to miss -
never in an exception message either. httpx raises errors that quote the URL
they failed against, and those propagate to a caller that logs them with a
traceback, so a failed POST would publish the token to `syswatch.log`. The
failures raised here name the status and nothing else.

One leak is not this module's to close: httpx logs every request it makes, at
INFO, with the full URL. app/logging_config.py holds that logger at WARNING -
originally to stop 8,640 lines a day of successful polls, and now also because
it is what keeps a webhook token out of syswatch.log. Anyone lowering it to
debug a request should know they are turning that off as well.
"""
import httpx

from app.alerts.notifier import Notifier
from app.models.alert import Alert

# The same reasoning as the SMTP timeout: deliver() runs on the poller's
# thread, and an endpoint that accepts a connection then stops reading would
# otherwise stall collection.
TIMEOUT_SECONDS = 10


class WebhookNotifier(Notifier):
    """POST one JSON document per alert state change."""

    def __init__(self, *, url, timeout=TIMEOUT_SECONDS):
        self._url = url
        self._timeout = timeout

    def __repr__(self):
        # No URL. The default repr would print it, and it is a secret.
        return "WebhookNotifier(url=<configured>)"

    def deliver(self, change, alert):
        try:
            response = httpx.post(
                self._url, json=self._payload(change, alert), timeout=self._timeout
            )
        except httpx.HTTPError as error:
            # Every transport failure, re-raised without the URL. httpx carries
            # the request on its exceptions and names the URL in the chain, and
            # `raise ... from None` drops that chain rather than letting the
            # caller's traceback publish the token.
            #
            # Catching the base class rather than the ones worth listing: the
            # set of things httpx can raise is not this module's to keep up
            # with, and a new one appearing should not become a leak.
            raise RuntimeError(
                f"the webhook could not be reached: {type(error).__name__}"
            ) from None

        if response.is_success:
            return

        # Deliberately not response.raise_for_status(): httpx puts the URL in
        # that message too.
        raise RuntimeError(f"the webhook answered {response.status_code}")

    def _payload(self, change, alert):
        """The alert as the API serves it, under the change that produced it.

        Reusing Alert.from_record means a consumer reads one schema rather than
        two, and a field added to the API arrives here without anyone
        remembering to add it.

        `change` is strictly redundant - `alert.state` is "firing" on an
        opening and "ok" on a resolution - but a consumer should not have to
        infer the event from the state, and later events will not all be
        deducible that way.
        """
        return {
            "change": change,
            "alert": Alert.from_record(alert).model_dump(mode="json"),
        }
