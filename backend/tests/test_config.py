import pytest
from pydantic import ValidationError

from config import Settings, get_settings

ENV_VARS = ("SYSWATCH_HOST", "SYSWATCH_PORT", "SYSWATCH_AGENT_BASE_URL")


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
