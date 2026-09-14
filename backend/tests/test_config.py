import pytest
from pydantic import ValidationError

from config import Settings, get_settings

ENV_VARS = (
    "SYSWATCH_HOST",
    "SYSWATCH_PORT",
    "SYSWATCH_AGENT_BASE_URL",
    "SYSWATCH_DATABASE_URL",
    "SYSWATCH_POLLING_ENABLED",
    "SYSWATCH_POLL_INTERVAL_SECONDS",
    "SYSWATCH_RETENTION_DAYS",
    "SYSWATCH_CORS_ORIGINS",
    "SYSWATCH_ALERTS_ENABLED",
    "SYSWATCH_DATA_DIR",
    "SYSWATCH_LOG_DIR",
    "SYSWATCH_LOG_LEVEL",
    "SYSWATCH_DEV_MODE",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Drop any SYSWATCH_ vars inherited from the developer's shell."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_settings_use_documented_defaults(clean_env):
    settings = Settings()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.agent_base_url == "http://127.0.0.1:8080"


def test_settings_read_prefixed_env_vars(clean_env):
    clean_env.setenv("SYSWATCH_HOST", "0.0.0.0")
    clean_env.setenv("SYSWATCH_PORT", "9000")
    clean_env.setenv("SYSWATCH_AGENT_BASE_URL", "http://10.0.0.5:9090")

    settings = Settings()

    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.agent_base_url == "http://10.0.0.5:9090"


def test_settings_ignore_unprefixed_env_vars(clean_env):
    clean_env.setenv("HOST", "10.1.1.1")
    clean_env.setenv("PORT", "1234")

    settings = Settings()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000


def test_settings_env_names_are_case_insensitive(clean_env):
    # Only meaningful on case-sensitive platforms: Windows folds env var names
    # in the OS, so this passes there even with case_sensitive=True.
    clean_env.setenv("syswatch_host", "192.168.1.10")

    assert Settings().host == "192.168.1.10"


def test_settings_coerce_port_to_int(clean_env):
    clean_env.setenv("SYSWATCH_PORT", "9001")

    port = Settings().port

    assert port == 9001
    assert isinstance(port, int)


def test_settings_reject_non_numeric_port(clean_env):
    clean_env.setenv("SYSWATCH_PORT", "not-a-port")

    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_reads_environment_at_call_time(clean_env):
    clean_env.setenv("SYSWATCH_PORT", "8123")

    assert get_settings().port == 8123


def test_database_settings_use_documented_defaults(clean_env):
    settings = Settings()

    # Derived from the data directory rather than the working directory: a
    # Windows Service starts in C:\Windows\System32.
    assert settings.database_url.startswith("sqlite:///")
    assert settings.database_url.endswith("/syswatch.db")
    assert settings.data_dir in settings.log_dir
    assert settings.polling_enabled is True
    assert settings.poll_interval_seconds == 10.0
    assert settings.retention_days == 30
    assert settings.alerts_enabled is True


@pytest.mark.parametrize("value, expected", [("false", False), ("0", False), ("true", True)])
def test_alerts_can_be_toggled_by_env(clean_env, value, expected):
    clean_env.setenv("SYSWATCH_ALERTS_ENABLED", value)

    assert Settings().alerts_enabled is expected


def test_database_settings_read_prefixed_env_vars(clean_env):
    clean_env.setenv("SYSWATCH_DATABASE_URL", "sqlite:///./other.db")
    clean_env.setenv("SYSWATCH_POLL_INTERVAL_SECONDS", "2.5")
    clean_env.setenv("SYSWATCH_RETENTION_DAYS", "7")

    settings = Settings()

    assert settings.database_url == "sqlite:///./other.db"
    assert settings.poll_interval_seconds == 2.5
    assert settings.retention_days == 7


@pytest.mark.parametrize("value", ["false", "False", "0", "no"])
def test_polling_can_be_disabled_by_env(clean_env, value):
    clean_env.setenv("SYSWATCH_POLLING_ENABLED", value)

    assert Settings().polling_enabled is False


@pytest.mark.parametrize("value", ["true", "True", "1", "yes"])
def test_polling_can_be_enabled_by_env(clean_env, value):
    clean_env.setenv("SYSWATCH_POLLING_ENABLED", value)

    assert Settings().polling_enabled is True


@pytest.mark.parametrize(
    "name, value",
    [
        ("SYSWATCH_POLL_INTERVAL_SECONDS", "often"),
        ("SYSWATCH_RETENTION_DAYS", "forever"),
        ("SYSWATCH_POLLING_ENABLED", "maybe"),
    ],
)
def test_invalid_values_are_rejected_at_startup(clean_env, name, value):
    clean_env.setenv(name, value)

    # Failing loudly beats silently falling back to a default and collecting
    # on the wrong schedule.
    with pytest.raises(ValidationError):
        Settings()


# --- credentials must not leak through a repr --------------------------------

SECRETS = [
    ("SYSWATCH_SESSION_SECRET", "session-secret-do-not-print"),
    ("SYSWATCH_SMTP_PASSWORD", "smtp-password-do-not-print"),
    ("SYSWATCH_WEBHOOK_URL", "https://hooks.example.com/T000/token-do-not-print"),
]


@pytest.mark.parametrize("name, value", SECRETS)
def test_a_credential_never_appears_in_the_repr(clean_env, name, value):
    """Printing the settings must not be a way to lose a secret.

    These were documented as "never repr'd" while being plain strings that
    pydantic printed like any other field. Nothing in the application printed a
    Settings, so nothing leaked - but that is a fact about today's code, not a
    property of this class, and the two files involved are not protected alike:
    syswatch.env is restricted to Administrators and SYSTEM, while the log
    beside it is readable by every account on the machine.
    """
    clean_env.setenv(name, value)

    settings = Settings()

    assert value not in repr(settings)
    assert value not in str(settings)
    assert value not in f"{settings}"


@pytest.mark.parametrize("name, value", SECRETS)
def test_the_value_is_still_readable_by_name(clean_env, name, value):
    """Redacted in the repr, not withheld from the code that needs it."""
    clean_env.setenv(name, value)

    settings = Settings()
    field = name.removeprefix("SYSWATCH_").lower()

    assert getattr(settings, field) == value


def test_the_repr_still_shows_what_it_is_for(clean_env):
    """A repr that redacted everything would just be useless instead of unsafe."""
    clean_env.setenv("SYSWATCH_PORT", "9123")

    text = repr(Settings())

    assert "9123" in text
    assert "127.0.0.1" in text


def test_an_unset_credential_is_not_redacted_into_looking_set(clean_env):
    """`***` against an empty field would claim a credential that is not there.

    Reading "smtp_password='***'" while debugging mail that never sends would
    send somebody looking for a wrong password rather than a missing one.
    """
    text = repr(Settings())

    assert "smtp_password=''" in text
    assert "webhook_url=''" in text
