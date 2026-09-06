import logging

import httpx
import pytest
import respx
from alert_doubles import FakeAlertStore, FakeRuleStore, make_snapshot, rule

from app.alerts import AlertEngine, build_notifier
from app.alerts.notifier import OPENED, RESOLVED
from app.alerts.webhook import WebhookNotifier

# A Slack-shaped URL: the secret is in the path, which is the whole reason this
# module treats a URL like a credential.
URL = "https://hooks.example.test/services/T00000/B00000/hV3ryS3cr3tT0k3n"
TOKEN = "hV3ryS3cr3tT0k3n"


def an_alert(store=None, **overrides):
    store = store or FakeAlertStore()
    fields = {"id": 7, "name": "CPU usage high", "metric": "cpu",
              "operator": "gt", "threshold": 80.0, "severity": "warning"}
    fields.update(overrides)
    return store.open_new(
        rule=rule(**fields), host_name="devbox", value=91.5,
        at=make_snapshot().collectedAt,
    )


def transports_of(built):
    """The transports inside a built notifier, past the severity filters."""
    from app.alerts.notifier import SeverityFilter

    return [
        n._notifier if isinstance(n, SeverityFilter) else n
        for n in built._notifiers
    ]


def assert_module_cannot_log(module_name):
    """The file that holds a secret must contain nothing that can write a log.

    Checked on the imports and the call, not on the word "logger" - the
    docstrings in these modules explain at length why they have no logger, and
    a substring search finds that explanation and calls it a violation.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "alerts" / module_name
    ).read_text(encoding="utf-8")

    code = chr(10).join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    body = code.split('"""')[-1]  # past the module docstring

    assert "import logging" not in code
    assert "getLogger" not in code
    assert "logger" not in body


# --- the payload ------------------------------------------------------------


@respx.mock
def test_an_opened_alert_is_posted_as_the_api_shape():
    route = respx.post(URL).respond(200)

    WebhookNotifier(url=URL).deliver(OPENED, an_alert())

    assert route.called
    body = route.calls[0].request.read()
    import json

    payload = json.loads(body)

    assert payload["change"] == "opened"
    alert = payload["alert"]
    # camelCase, exactly as GET /api/alerts serves it - not the record's
    # snake_case, which is an internal detail.
    assert alert["ruleName"] == "CPU usage high"
    assert alert["hostName"] == "devbox"
    assert alert["value"] == 91.5
    assert alert["threshold"] == 80.0
    assert alert["severity"] == "warning"
    assert alert["state"] == "firing"


@respx.mock
def test_a_resolution_is_posted_with_the_resolved_alert():
    route = respx.post(URL).respond(204)
    store = FakeAlertStore()
    alert = an_alert(store)
    resolved = store.resolve(alert_id=alert.id, value=12.0, at=alert.triggered_at)

    WebhookNotifier(url=URL).deliver(RESOLVED, resolved)

    import json

    payload = json.loads(route.calls[0].request.read())
    assert payload["change"] == "resolved"
    assert payload["alert"]["state"] == "ok"
    assert payload["alert"]["resolvedAt"] is not None


@respx.mock
def test_the_payload_is_json_serialisable_end_to_end():
    """model_dump(mode="json") - a datetime left as an object would raise here."""
    route = respx.post(URL).respond(200)

    WebhookNotifier(url=URL).deliver(OPENED, an_alert())

    import json

    payload = json.loads(route.calls[0].request.read())
    assert isinstance(payload["alert"]["triggeredAt"], str)


# --- failures ---------------------------------------------------------------


@respx.mock
def test_a_non_2xx_response_is_a_failure():
    respx.post(URL).respond(500)

    with pytest.raises(RuntimeError, match="answered 500"):
        WebhookNotifier(url=URL).deliver(OPENED, an_alert())


@respx.mock
def test_a_202_is_success():
    """Plenty of receivers accept and queue."""
    respx.post(URL).respond(202)

    WebhookNotifier(url=URL).deliver(OPENED, an_alert())


@respx.mock
def test_a_failing_webhook_does_not_disturb_the_poller(caplog):
    respx.post(URL).respond(503)

    engine = AlertEngine(
        FakeRuleStore(rule(id=1, metric="cpu", operator="gt", threshold=80)),
        FakeAlertStore(),
        notifier=WebhookNotifier(url=URL),
    )

    with caplog.at_level(logging.WARNING):
        summary = engine.evaluate(make_snapshot(cpu_usage=95))

    assert summary.opened == 1  # the alert is still recorded
    assert "Could not deliver" in caplog.text


@respx.mock
def test_a_timeout_is_bounded():
    """deliver() runs on the poller's thread."""
    route = respx.post(URL).respond(200)

    WebhookNotifier(url=URL).deliver(OPENED, an_alert())

    assert route.calls[0].request.extensions["timeout"]["connect"] == 10


# --- the URL is a secret ----------------------------------------------------


def test_the_url_is_not_in_the_repr():
    assert TOKEN not in repr(WebhookNotifier(url=URL))


@respx.mock
def test_a_rejected_post_does_not_put_the_url_in_the_log(caplog):
    """httpx.raise_for_status() quotes the URL. That is why it is not used."""
    respx.post(URL).respond(403)

    engine = AlertEngine(
        FakeRuleStore(rule(id=1, metric="cpu", operator="gt", threshold=80)),
        FakeAlertStore(),
        notifier=WebhookNotifier(url=URL),
    )

    with caplog.at_level(logging.WARNING):
        engine.evaluate(make_snapshot(cpu_usage=95))

    assert "answered 403" in caplog.text
    assert TOKEN not in caplog.text


@respx.mock
def test_a_connection_failure_does_not_put_the_url_in_the_log(caplog):
    """The other path: httpx's own transport errors also name the URL."""
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))

    engine = AlertEngine(
        FakeRuleStore(rule(id=1, metric="cpu", operator="gt", threshold=80)),
        FakeAlertStore(),
        notifier=WebhookNotifier(url=URL),
    )

    with caplog.at_level(logging.WARNING):
        engine.evaluate(make_snapshot(cpu_usage=95))

    assert "Could not deliver" in caplog.text
    assert TOKEN not in caplog.text


def test_the_webhook_module_has_no_logger():
    """The surest way a secret never reaches a log."""
    assert_module_cannot_log("webhook.py")


# --- assembly ---------------------------------------------------------------


def test_no_url_means_no_webhook():
    from config import Settings

    built = build_notifier(Settings())

    assert not any(isinstance(n, WebhookNotifier) for n in transports_of(built))


def test_a_configured_url_adds_the_transport():
    from config import Settings

    built = build_notifier(Settings(webhook_url=URL))

    assert any(isinstance(n, WebhookNotifier) for n in transports_of(built))
    assert TOKEN not in repr(built)


def test_the_token_does_not_reach_the_log_through_httpx(tmp_path, monkeypatch):
    r"""The one leak this module cannot close on its own.

    httpx logs every request it makes, at INFO, with the full URL. This module
    never names the URL, but that counts for nothing if another module's logger
    prints it - so the protection is app/logging_config.py holding httpx at
    WARNING, and this is what fails if somebody lowers it.

    Checked at DEBUG deliberately: the most permissive setting an operator can
    choose is the one under which the guarantee has to hold.
    """
    import logging as std_logging

    from app.logging_config import configure_logging
    from config import Settings

    settings = Settings(log_dir=str(tmp_path), log_level="DEBUG", dev_mode=True)
    path = configure_logging(settings)

    with respx.mock:
        respx.post(URL).respond(200)
        WebhookNotifier(url=URL).deliver(OPENED, an_alert())

    std_logging.shutdown()

    assert TOKEN not in path.read_text(encoding="utf-8", errors="replace")
