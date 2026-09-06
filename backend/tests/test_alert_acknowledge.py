from datetime import datetime, timedelta, timezone

import pytest

from app.models.alert import Alert, AlertRuleCreate
from app.repositories import AlertRuleStore, AlertStore

AT = datetime(2026, 9, 6, 11, 0, tzinfo=timezone.utc)


@pytest.fixture
def firing_alert(database):
    """One open alert, opened the way the engine opens them."""
    rule = AlertRuleStore().create(
        AlertRuleCreate(
            name="CPU usage high",
            metric="cpu",
            operator="gt",
            threshold=80.0,
            severity="critical",
        )
    )
    return AlertStore().open_new(rule=rule, host_name="devbox", value=91.5, at=AT)


# --- the store --------------------------------------------------------------


def test_acknowledging_records_who_and_when(firing_alert):
    acknowledged = AlertStore().acknowledge(
        alert_id=firing_alert.id, username="sam", at=AT
    )

    assert acknowledged.acknowledged_by == "sam"
    assert acknowledged.acknowledged_at == AT


def test_an_acknowledged_alert_stays_open(firing_alert):
    """"I know, I am dealing with it" - not "this is over".

    Closing it would lose the state the operator acknowledged, and the
    condition is still true.
    """
    store = AlertStore()
    acknowledged = store.acknowledge(alert_id=firing_alert.id, username="sam", at=AT)

    assert acknowledged.state == "firing"
    assert acknowledged.resolved_at is None
    assert [alert.id for alert in store.active("devbox")] == [firing_alert.id]


def test_an_unacknowledged_alert_says_so(firing_alert):
    assert firing_alert.acknowledged_at is None
    assert firing_alert.acknowledged_by is None


def test_acknowledging_twice_keeps_the_first_person(firing_alert):
    """Who picked it up is whoever got there first."""
    store = AlertStore()
    store.acknowledge(alert_id=firing_alert.id, username="sam", at=AT)

    later = store.acknowledge(
        alert_id=firing_alert.id, username="alex", at=AT + timedelta(hours=1)
    )

    assert later.acknowledged_by == "sam"
    assert later.acknowledged_at == AT


def test_acknowledging_an_alert_that_does_not_exist_returns_nothing(database):
    assert AlertStore().acknowledge(alert_id=999, username="sam") is None


def test_a_resolved_alert_can_still_be_acknowledged(firing_alert):
    """The condition cleared before anyone looked; the record still says who did."""
    store = AlertStore()
    store.resolve(alert_id=firing_alert.id, value=10.0, at=AT)

    acknowledged = store.acknowledge(alert_id=firing_alert.id, username="sam", at=AT)

    assert acknowledged.acknowledged_by == "sam"
    assert acknowledged.state == "ok"


def test_acknowledging_one_alert_leaves_the_others_alone(firing_alert):
    store = AlertStore()
    rule = AlertRuleStore().create(
        AlertRuleCreate(
            name="Memory usage high", metric="memory", operator="gt", threshold=80.0
        )
    )
    other = store.open_new(rule=rule, host_name="devbox", value=95.0, at=AT)

    store.acknowledge(alert_id=firing_alert.id, username="sam", at=AT)

    assert store.get(other.id).acknowledged_by is None


# --- the API ----------------------------------------------------------------


def test_the_endpoint_acknowledges_as_the_caller(admin_client, firing_alert):
    response = admin_client.post(f"/alerts/{firing_alert.id}/acknowledge")

    assert response.status_code == 200
    body = response.json()
    assert body["acknowledgedBy"] == "test-admin"
    assert body["acknowledgedAt"] is not None
    assert body["state"] == "firing"


def test_a_viewer_can_acknowledge(viewer_client, firing_alert):
    """Not an admin-only action.

    Acknowledging is not a configuration change - it is the person on shift
    saying they have seen it. Requiring a role would leave a viewer watching an
    alert they cannot answer.
    """
    response = viewer_client.post(f"/alerts/{firing_alert.id}/acknowledge")

    assert response.status_code == 200
    assert response.json()["acknowledgedBy"] == "test-viewer"


def test_acknowledging_needs_a_session(anon_client, firing_alert):
    response = anon_client.post(f"/alerts/{firing_alert.id}/acknowledge")

    assert response.status_code == 401


def test_acknowledging_a_missing_alert_is_a_404(admin_client, database):
    assert admin_client.post("/alerts/999/acknowledge").status_code == 404


def test_the_acknowledgement_shows_up_when_the_alert_is_read_back(
    admin_client, firing_alert
):
    admin_client.post(f"/alerts/{firing_alert.id}/acknowledge")

    body = admin_client.get(f"/alerts/{firing_alert.id}").json()

    assert body["acknowledgedBy"] == "test-admin"


def test_an_unacknowledged_alert_serialises_as_null(admin_client, firing_alert):
    body = admin_client.get(f"/alerts/{firing_alert.id}").json()

    assert body["acknowledgedAt"] is None
    assert body["acknowledgedBy"] is None


def test_the_model_carries_the_fields_from_the_record(firing_alert):
    acknowledged = AlertStore().acknowledge(
        alert_id=firing_alert.id, username="sam", at=AT
    )

    model = Alert.from_record(acknowledged)

    assert model.acknowledgedBy == "sam"
    assert model.acknowledgedAt == AT


@pytest.fixture
def file_backed_database(tmp_path):
    """A database several threads can use at once.

    The suite's default is in-memory, which SQLAlchemy backs with a StaticPool:
    one connection shared by every session, because each connection to
    ":memory:" would otherwise get a private database. Threads contending on
    one connection produce "bad parameter or other API misuse", which is a
    property of the fixture and not of anything that ships.
    """
    from app.db import session as db_session
    from app.db.models import Base

    db_session.dispose_engine()
    engine = db_session.init_engine(
        f"sqlite:///{(tmp_path / 'contention.db').as_posix()}"
    )
    Base.metadata.create_all(engine)

    yield

    db_session.dispose_engine()


def test_the_first_acknowledgement_wins_even_under_contention(file_backed_database):
    """The claim in acknowledge()'s docstring, made true by SQL rather than luck.

    Checking in Python and then writing is a read-modify-write: two callers
    both see NULL, both write, and the later one wins - the opposite of what
    the method promises. The WHERE clause makes the second update match no
    rows.
    """
    import threading

    rule = AlertRuleStore().create(
        AlertRuleCreate(name="CPU usage high", metric="cpu", operator="gt", threshold=80.0)
    )
    alert = AlertStore().open_new(rule=rule, host_name="devbox", value=91.5, at=AT)

    store = AlertStore()
    told = []
    start = threading.Barrier(6)

    def acknowledge(who):
        start.wait()
        told.append(store.acknowledge(alert_id=alert.id, username=who))

    threads = [threading.Thread(target=acknowledge, args=(f"user{n}",)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Every caller was told the same thing, and it is what the row says.
    names = {alert.acknowledged_by for alert in told}
    assert len(names) == 1
    assert names.pop() == store.get(alert.id).acknowledged_by
