"""The authorization matrix, against the real application.

This is the test that makes the dashboard's role-aware UI a courtesy rather
than a control: whatever the browser chooses to render, these are the answers
the server gives.

Every case asserts the authorization outcome only. Whether a route then returns
200, 404 or 503 is its own file's business — GET /snapshot, for instance,
reaches for an agent that is not running.
"""
import pytest

AUTHENTICATED_ROUTES = [
    ("GET", "/status"),
    ("GET", "/snapshot"),
    ("GET", "/snapshots"),
    ("GET", "/snapshots/latest"),
    ("GET", "/snapshots/series?metric=cpu"),
    ("GET", "/hosts"),
    ("GET", "/alerts"),
    ("GET", "/alerts/active"),
    ("GET", "/alerts/1"),
    ("GET", "/alert-rules"),
]

NEW_RULE = {
    "name": "CPU critical",
    "metric": "cpu",
    "operator": "gt",
    "threshold": 95,
    "severity": "critical",
}

ADMIN_ONLY_ROUTES = [
    ("POST", "/alert-rules", NEW_RULE),
    ("PUT", "/alert-rules/1", {"enabled": False}),
    ("DELETE", "/alert-rules/1", None),
]

PUBLIC_ROUTES = [
    ("GET", "/health"),
]


def call(client, method, path, body=None):
    return client.request(method, path, json=body)


# --- anonymous --------------------------------------------------------------


@pytest.mark.parametrize("method, path", AUTHENTICATED_ROUTES)
def test_an_anonymous_caller_cannot_read_anything(anon_client, method, path):
    assert call(anon_client, method, path).status_code == 401


@pytest.mark.parametrize("method, path, body", ADMIN_ONLY_ROUTES)
def test_an_anonymous_caller_cannot_write_rules(anon_client, method, path, body):
    # 401 rather than 403: the chain asks who you are before whether you may.
    assert call(anon_client, method, path, body).status_code == 401


@pytest.mark.parametrize("method, path", PUBLIC_ROUTES)
def test_the_public_routes_stay_public(anon_client, method, path):
    # /health answers one question — is this process alive — and a load
    # balancer asking it has no session to offer.
    assert call(anon_client, method, path).status_code == 200


def test_an_anonymous_caller_can_still_reach_login(anon_client):
    response = anon_client.post(
        "/auth/login", json={"username": "nobody", "password": "irrelevant"}
    )

    # 401 for bad credentials, not 401 for missing a session — the difference
    # is that this route was reachable at all.
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


# --- viewer -----------------------------------------------------------------


@pytest.mark.parametrize("method, path", AUTHENTICATED_ROUTES)
def test_a_viewer_may_read_everything(viewer_client, method, path):
    assert call(viewer_client, method, path).status_code not in (401, 403)


@pytest.mark.parametrize("method, path, body", ADMIN_ONLY_ROUTES)
def test_a_viewer_may_not_write_rules(viewer_client, method, path, body):
    response = call(viewer_client, method, path, body)

    assert response.status_code == 403
    assert response.json()["detail"] == "Administrator access required"


def test_a_viewer_is_refused_before_the_rule_is_even_looked_up(viewer_client):
    # Rule 9999 does not exist. A 404 here would tell a viewer which rule ids
    # are real; the role check has to come first.
    assert call(viewer_client, "DELETE", "/alert-rules/9999").status_code == 403


# --- admin ------------------------------------------------------------------


@pytest.mark.parametrize("method, path", AUTHENTICATED_ROUTES)
def test_an_admin_may_read_everything(admin_client, method, path):
    assert call(admin_client, method, path).status_code not in (401, 403)


@pytest.mark.parametrize("method, path, body", ADMIN_ONLY_ROUTES)
def test_an_admin_is_never_refused_on_authorization(admin_client, method, path, body):
    assert call(admin_client, method, path, body).status_code not in (401, 403)


def test_an_admin_can_run_the_whole_rule_lifecycle(admin_client):
    created = admin_client.post("/alert-rules", json=NEW_RULE)
    assert created.status_code == 201
    rule_id = created.json()["id"]

    assert admin_client.put(f"/alert-rules/{rule_id}", json={"enabled": False}).status_code == 200
    assert admin_client.delete(f"/alert-rules/{rule_id}").status_code == 204


# --- losing the session -----------------------------------------------------


def test_logging_out_takes_the_access_with_it(admin_client):
    assert admin_client.get("/alerts").status_code == 200

    admin_client.post("/auth/logout")

    # What the dashboard sees when a session ends under it, and what sends it
    # back to the login page.
    assert admin_client.get("/alerts").status_code == 401
