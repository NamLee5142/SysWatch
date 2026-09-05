"""The shared test harness, checked directly.

A broken client fixture would show up as a confusing failure in whatever test
happened to use it next, so it is worth proving here that each one is who it
claims to be.
"""
from fastapi.testclient import TestClient

from app.main import create_app
from conftest import ADMIN_USERNAME, VIEWER_USERNAME


def test_anon_client_has_no_session(anon_client):
    assert anon_client.get("/auth/me").status_code == 401


def test_admin_client_is_logged_in_as_an_admin(admin_client):
    body = admin_client.get("/auth/me").json()

    assert body == {"username": ADMIN_USERNAME, "role": "admin"}


def test_viewer_client_is_logged_in_as_a_viewer(viewer_client):
    body = viewer_client.get("/auth/me").json()

    assert body == {"username": VIEWER_USERNAME, "role": "viewer"}


def test_the_clients_do_not_share_a_session(admin_client, viewer_client):
    assert admin_client.get("/auth/me").json()["role"] == "admin"
    assert viewer_client.get("/auth/me").json()["role"] == "viewer"


def test_a_test_that_asks_for_no_client_runs_without_authentication(database):
    # The autouse bypass: a test about snapshots or alerts should not have to
    # know that authentication exists. The dependency still runs — it resolves
    # to the anonymous admin rather than being skipped.
    client = TestClient(create_app(), base_url="http://testserver/api")

    body = client.get("/auth/me").json()

    assert body == {"username": "anonymous", "role": "admin"}
