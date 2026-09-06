from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories import AlertRuleStore, AlertStore

app = create_app()
client = TestClient(app, base_url="http://testserver/api")

VALID_RULE = {
    "name": "CPU critical",
    "metric": "cpu",
    "operator": "gt",
    "threshold": 95,
    "severity": "critical",
}


pytestmark = pytest.mark.usefixtures("database")


def test_list_is_empty_on_a_fresh_database():
    assert client.get("/alert-rules").json() == {"items": []}


def test_create_returns_201_and_the_stored_rule():
    response = client.post("/alert-rules", json=VALID_RULE)

    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["name"] == "CPU critical"
    assert body["enabled"] is True
    assert body["createdAt"].endswith("Z")

    assert [r["name"] for r in client.get("/alert-rules").json()["items"]] == ["CPU critical"]


def test_create_defaults_severity_and_enabled():
    response = client.post(
        "/alert-rules",
        json={"name": "x", "metric": "memory", "operator": "gt", "threshold": 90},
    )

    body = response.json()
    assert body["severity"] == "warning"
    assert body["enabled"] is True


@pytest.mark.parametrize(
    "bad",
    [
        {**VALID_RULE, "name": "   "},
        {**VALID_RULE, "metric": "gpu"},
        {**VALID_RULE, "operator": "=="},
        {**VALID_RULE, "severity": "meh"},
        {k: v for k, v in VALID_RULE.items() if k != "threshold"},
    ],
)
def test_create_rejects_an_invalid_rule(bad):
    assert client.post("/alert-rules", json=bad).status_code == 422


def test_update_applies_only_the_sent_fields():
    rule_id = client.post("/alert-rules", json=VALID_RULE).json()["id"]

    response = client.put(f"/alert-rules/{rule_id}", json={"enabled": False})

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["threshold"] == 95  # untouched
    assert body["updatedAt"] >= body["createdAt"]


def test_update_of_a_missing_rule_is_404():
    response = client.put("/alert-rules/999", json={"enabled": False})

    assert response.status_code == 404
    assert response.json()["detail"] == "No alert rule with that id"


def test_update_with_an_empty_body_is_422():
    rule_id = client.post("/alert-rules", json=VALID_RULE).json()["id"]

    assert client.put(f"/alert-rules/{rule_id}", json={}).status_code == 422


def test_update_rejects_an_invalid_value():
    rule_id = client.post("/alert-rules", json=VALID_RULE).json()["id"]

    assert client.put(f"/alert-rules/{rule_id}", json={"operator": "!="}).status_code == 422


def test_delete_returns_204_and_removes_the_rule():
    rule_id = client.post("/alert-rules", json=VALID_RULE).json()["id"]

    response = client.delete(f"/alert-rules/{rule_id}")

    assert response.status_code == 204
    assert client.get("/alert-rules").json() == {"items": []}


def test_delete_of_a_missing_rule_is_404():
    assert client.delete("/alert-rules/999").status_code == 404


def test_deleting_a_rule_keeps_its_alerts_as_history():
    rule = AlertRuleStore().create(
        SimpleNamespace(
            name="CPU critical", metric="cpu", operator="gt", threshold=95,
            severity="critical", enabled=True,
        )
    )
    alert = AlertStore().open_new(
        rule=rule, host_name="devbox", value=99.0,
        at=datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
    )

    assert client.delete(f"/alert-rules/{rule.id}").status_code == 204

    orphan = client.get(f"/alerts/{alert.id}").json()
    assert orphan["ruleId"] is None
    assert orphan["ruleName"] == "CPU critical"
