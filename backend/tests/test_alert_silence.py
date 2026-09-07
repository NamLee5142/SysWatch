from datetime import datetime, timedelta, timezone

import pytest
from alert_doubles import FakeAlertStore, FakeRuleStore, make_snapshot, rule

from app.alerts import AlertEngine
from app.alerts.notifier import OPENED, RESOLVED, Notifier
from app.models.alert import AlertRule, AlertRuleCreate
from app.repositories import AlertRuleStore

NOW = datetime.now(timezone.utc)


def parse_api_time(value):
    """Read a timestamp the way the API serves it.

    The API spells UTC with a trailing Z. datetime.fromisoformat did not accept
    that until Python 3.11, and the installer accepts 3.10 - so the plain call
    raises "Invalid isoformat string" on the oldest interpreter this project
    supports, and only there. Substituting the offset it stands for parses on
    every version.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Recorder(Notifier):
    def __init__(self):
        self.delivered = []

    def deliver(self, change, alert):
        self.delivered.append(change)


def silenced_rule(until, **overrides):
    made = rule(id=1, metric="cpu", operator="gt", threshold=80.0, **overrides)
    made.silenced_until = until
    return made


def engine_for(rules, notifier, alert_store=None):
    return AlertEngine(
        FakeRuleStore(*rules), alert_store or FakeAlertStore(), notifier=notifier
    )


# --- the engine -------------------------------------------------------------


def test_a_silenced_rule_sends_nothing():
    recorder = Recorder()
    engine = engine_for([silenced_rule(NOW + timedelta(hours=1))], recorder)

    engine.evaluate(make_snapshot(cpu_usage=95))

    assert recorder.delivered == []


def test_a_silenced_rule_still_evaluates_and_still_records():
    """Silencing is not a quieter way of disabling a rule.

    History stays complete and the dashboard still shows what is firing; only
    the outbound message is withheld.
    """
    store = FakeAlertStore()
    engine = engine_for([silenced_rule(NOW + timedelta(hours=1))], Recorder(), store)

    summary = engine.evaluate(make_snapshot(cpu_usage=95))

    assert summary.opened == 1
    assert len(store.active("devbox")) == 1


def test_a_silenced_rule_says_nothing_when_it_resolves_either():
    recorder = Recorder()
    engine = engine_for([silenced_rule(NOW + timedelta(hours=1))], recorder)

    engine.evaluate(make_snapshot(cpu_usage=95))
    engine.evaluate(make_snapshot(cpu_usage=5))

    assert recorder.delivered == []


def test_an_expired_silence_is_no_silence():
    recorder = Recorder()
    engine = engine_for([silenced_rule(NOW - timedelta(minutes=1))], recorder)

    engine.evaluate(make_snapshot(cpu_usage=95))

    assert recorder.delivered == [OPENED]


def test_a_rule_that_was_never_silenced_is_unaffected():
    recorder = Recorder()
    engine = engine_for([silenced_rule(None)], recorder)

    engine.evaluate(make_snapshot(cpu_usage=95))

    assert recorder.delivered == [OPENED]


def test_silencing_one_rule_does_not_silence_another():
    recorder = Recorder()
    quiet = silenced_rule(NOW + timedelta(hours=1))
    loud = rule(id=2, metric="cpu", operator="gt", threshold=90.0)
    loud.silenced_until = None

    engine_for([quiet, loud], recorder).evaluate(make_snapshot(cpu_usage=95))

    assert recorder.delivered == [OPENED]


def test_the_silence_ends_and_the_next_change_is_announced():
    """The expiry is real, not a one-way switch."""
    recorder = Recorder()
    silenced = silenced_rule(NOW + timedelta(hours=1))
    engine = engine_for([silenced], recorder)

    engine.evaluate(make_snapshot(cpu_usage=95))
    assert recorder.delivered == []

    silenced.silenced_until = NOW - timedelta(seconds=1)
    engine.evaluate(make_snapshot(cpu_usage=5))

    assert recorder.delivered == [RESOLVED]


# --- the store --------------------------------------------------------------


@pytest.fixture
def a_rule(database):
    return AlertRuleStore().create(
        AlertRuleCreate(
            name="CPU usage high", metric="cpu", operator="gt", threshold=80.0
        )
    )


def test_silencing_records_the_expiry(a_rule):
    until = NOW + timedelta(hours=2)

    silenced = AlertRuleStore().silence(rule_id=a_rule.id, until=until)

    assert silenced.silenced_until == until


def test_a_new_rule_is_not_silenced(a_rule):
    assert a_rule.silenced_until is None


def test_silencing_again_replaces_the_expiry(a_rule):
    """An operator extending a maintenance window is doing the obvious thing."""
    store = AlertRuleStore()
    store.silence(rule_id=a_rule.id, until=NOW + timedelta(hours=1))

    extended = store.silence(rule_id=a_rule.id, until=NOW + timedelta(hours=4))

    assert extended.silenced_until == NOW + timedelta(hours=4)


def test_clearing_a_silence(a_rule):
    store = AlertRuleStore()
    store.silence(rule_id=a_rule.id, until=NOW + timedelta(hours=1))

    assert store.silence(rule_id=a_rule.id, until=None).silenced_until is None


def test_silencing_a_rule_that_does_not_exist(database):
    assert AlertRuleStore().silence(rule_id=999, until=NOW) is None


def test_silencing_leaves_the_rule_enabled(a_rule):
    """Different intentions. Disabling says the condition does not matter."""
    silenced = AlertRuleStore().silence(rule_id=a_rule.id, until=NOW + timedelta(hours=1))

    assert silenced.enabled is True


# --- the API ----------------------------------------------------------------


def test_silencing_takes_a_duration(admin_client, a_rule):
    response = admin_client.post(
        f"/alert-rules/{a_rule.id}/silence", json={"minutes": 90}
    )

    assert response.status_code == 200
    until = parse_api_time(response.json()["silencedUntil"])
    assert timedelta(minutes=88) < until - NOW < timedelta(minutes=92)


def test_a_silence_can_be_lifted_early(admin_client, a_rule):
    admin_client.post(f"/alert-rules/{a_rule.id}/silence", json={"minutes": 90})

    response = admin_client.delete(f"/alert-rules/{a_rule.id}/silence")

    assert response.status_code == 200
    assert response.json()["silencedUntil"] is None


@pytest.mark.parametrize("minutes", [0, -30, 60 * 24 * 40])
def test_a_nonsensical_duration_is_refused(admin_client, a_rule, minutes):
    """A silence until the past, or one nobody would remember setting."""
    response = admin_client.post(
        f"/alert-rules/{a_rule.id}/silence", json={"minutes": minutes}
    )

    assert response.status_code == 422


def test_silencing_is_admin_only(viewer_client, a_rule):
    """Acknowledging one alert is personal; silencing a rule decides for everybody."""
    assert (
        viewer_client.post(
            f"/alert-rules/{a_rule.id}/silence", json={"minutes": 60}
        ).status_code
        == 403
    )
    assert viewer_client.delete(f"/alert-rules/{a_rule.id}/silence").status_code == 403


def test_silencing_needs_a_session(anon_client, a_rule):
    assert (
        anon_client.post(
            f"/alert-rules/{a_rule.id}/silence", json={"minutes": 60}
        ).status_code
        == 401
    )


def test_silencing_a_missing_rule_is_a_404(admin_client, database):
    assert (
        admin_client.post("/alert-rules/999/silence", json={"minutes": 60}).status_code
        == 404
    )


def test_the_silence_shows_up_when_the_rule_is_listed(admin_client, a_rule):
    admin_client.post(f"/alert-rules/{a_rule.id}/silence", json={"minutes": 60})

    rules = admin_client.get("/alert-rules").json()["items"]
    listed = next(item for item in rules if item["id"] == a_rule.id)

    assert listed["silencedUntil"] is not None


def test_the_model_carries_the_field(a_rule):
    silenced = AlertRuleStore().silence(rule_id=a_rule.id, until=NOW + timedelta(hours=1))

    assert AlertRule.from_record(silenced).silencedUntil == NOW + timedelta(hours=1)
