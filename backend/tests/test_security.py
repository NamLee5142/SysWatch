import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.security import (
    API_CONTENT_SECURITY_POLICY,
    MIN_SESSION_SECRET_LENGTH,
    InsecureConfiguration,
    SecurityHeadersMiddleware,
    verify_security_configuration,
)
from config import Settings

SECRET = "a" * MIN_SESSION_SECRET_LENGTH


@pytest.fixture
def client(database):
    return TestClient(create_app())


# --- response headers -------------------------------------------------------


@pytest.mark.parametrize(
    "header, value",
    [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy", API_CONTENT_SECURITY_POLICY),
    ],
)
def test_every_response_carries_the_security_headers(client, header, value):
    assert client.get("/api/health").headers[header] == value


def test_the_headers_are_on_error_responses_too(client):
    # A 404 is still a response a browser will act on, and an attacker is far
    # more likely to be looking at one than at a 200.
    response = client.get("/no-such-route")

    assert response.status_code == 404
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == API_CONTENT_SECURITY_POLICY


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_the_documentation_is_absent_in_production(client, path):
    # A free, always-current map of every endpoint and request shape, offered
    # to anyone who can reach the port.
    assert client.get(path).status_code == 404


def test_the_documentation_ui_is_exempt_from_the_content_policy(database, monkeypatch):
    monkeypatch.setenv("SYSWATCH_DEV_MODE", "true")
    response = TestClient(create_app()).get("/docs")

    # default-src 'none' would blank Swagger UI, which loads its own scripts
    # and styles. The other headers still apply.
    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"


def test_a_route_may_set_its_own_policy(database):
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/custom")
    def custom():
        from fastapi.responses import JSONResponse

        return JSONResponse({}, headers={"X-Frame-Options": "SAMEORIGIN"})

    # setdefault, not overwrite: the middleware is a floor, not a ceiling.
    assert TestClient(app).get("/custom").headers["X-Frame-Options"] == "SAMEORIGIN"


# --- no tracebacks to the client -------------------------------------------


def test_debug_mode_is_off():
    # FastAPI's debug mode returns a traceback to the caller: file paths, local
    # variables and library versions, to anyone who can provoke a 500.
    assert create_app().debug is False


def test_an_unhandled_error_does_not_leak_its_traceback(database):
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/boom")
    def boom():
        raise RuntimeError("connection string: postgres://user:hunter2@db/prod")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")

    assert response.status_code == 500
    assert "hunter2" not in response.text
    assert "Traceback" not in response.text


# --- startup checks ---------------------------------------------------------


def settings(**overrides):
    base = {
        "auth_enabled": True,
        "dev_mode": False,
        "session_secret": SECRET,
    }
    base.update(overrides)
    return Settings(**base)


def test_a_good_configuration_warns_about_nothing():
    assert verify_security_configuration(settings()) == []


def test_a_missing_secret_refuses_to_start():
    with pytest.raises(InsecureConfiguration, match="SYSWATCH_SESSION_SECRET must be set"):
        verify_security_configuration(settings(session_secret=""))


def test_the_refusal_says_how_to_generate_one():
    with pytest.raises(InsecureConfiguration, match="token_urlsafe"):
        verify_security_configuration(settings(session_secret=""))


def test_a_short_secret_refuses_to_start():
    with pytest.raises(InsecureConfiguration, match="at least"):
        verify_security_configuration(settings(session_secret="tooshort"))


def test_dev_mode_allows_a_missing_secret_but_says_so():
    warnings = verify_security_configuration(settings(dev_mode=True, session_secret=""))

    assert any("SYSWATCH_DEV_MODE" in w for w in warnings)
    assert any("SYSWATCH_SESSION_SECRET is unset" in w for w in warnings)


def test_disabling_auth_is_fatal_outside_development():
    with pytest.raises(InsecureConfiguration, match="opens every endpoint"):
        verify_security_configuration(settings(auth_enabled=False, session_secret=""))


def test_the_refusal_says_how_to_allow_it():
    with pytest.raises(InsecureConfiguration, match="SYSWATCH_DEV_MODE=true"):
        verify_security_configuration(settings(auth_enabled=False, session_secret=""))


def test_disabling_auth_in_development_warns_instead():
    warnings = verify_security_configuration(
        settings(auth_enabled=False, dev_mode=True, session_secret="")
    )

    # A warning is right here and was not enough in production: a startup log
    # is a hundred lines of normal, and this one says the API is open to
    # anyone who can reach the port.
    assert any("every caller is treated as an administrator" in w for w in warnings)


def test_a_plain_http_cors_origin_is_refused():
    with pytest.raises(InsecureConfiguration, match="never send it"):
        verify_security_configuration(settings(cors_origins=["http://dash.example.com"]))


def test_an_https_cors_origin_is_fine():
    assert verify_security_configuration(settings(cors_origins=["https://dash.example.com"])) == []


def test_development_may_use_a_plain_http_origin():
    warnings = verify_security_configuration(
        settings(dev_mode=True, cors_origins=["http://localhost:5173"])
    )

    assert not any("never send it" in w for w in warnings)


def test_one_bad_origin_among_good_ones_is_still_refused():
    with pytest.raises(InsecureConfiguration):
        verify_security_configuration(
            settings(cors_origins=["https://good.example.com", "http://bad.example.com"])
        )


def test_the_startup_check_runs_in_the_lifespan(monkeypatch):
    monkeypatch.setenv("SYSWATCH_AUTH_ENABLED", "true")
    monkeypatch.setenv("SYSWATCH_SESSION_SECRET", "")
    monkeypatch.setenv("SYSWATCH_DATABASE_URL", "sqlite://")

    # Importing the app is fine; serving traffic with it is not.
    with pytest.raises(InsecureConfiguration):
        with TestClient(create_app()):
            pass
