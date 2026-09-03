"""Reading settings from a file.

A Windows Service has no shell to export from, so a secret has to live
somewhere it can be read at startup — while an operator overriding one value
for one run should not have to edit that file.
"""
from pathlib import Path

import pytest

from config import CONFIG_FILE_VAR, DEFAULT_CONFIG_FILE, Settings, config_file_path, get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = BACKEND_ROOT / "syswatch.env.example"


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Point the loader at a file this test controls."""

    def write(text):
        path = tmp_path / "syswatch.env"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv(CONFIG_FILE_VAR, str(path))
        return path

    for name in ("SYSWATCH_PORT", "SYSWATCH_AGENT_BASE_URL", "SYSWATCH_SESSION_SECRET"):
        monkeypatch.delenv(name, raising=False)

    return write


def test_a_value_is_read_from_the_file(config_file):
    config_file("SYSWATCH_PORT=9100\n")

    assert get_settings().port == 9100


def test_the_environment_wins_over_the_file(config_file, monkeypatch):
    config_file("SYSWATCH_PORT=9100\n")
    monkeypatch.setenv("SYSWATCH_PORT", "9200")

    # A one-off override on the command line must not need the file edited.
    assert get_settings().port == 9200


def test_comments_and_blank_lines_are_tolerated(config_file):
    config_file(
        "# the port to bind\n"
        "\n"
        "SYSWATCH_PORT=9300\n"
        "\n"
        "# SYSWATCH_PORT=9999   <- commented out, not applied\n"
    )

    assert get_settings().port == 9300


def test_an_unknown_key_does_not_stop_startup(config_file):
    config_file("SYSWATCH_PORT=9400\nSYSWATCH_SOMETHING_REMOVED=yes\n")

    # A key left behind by an upgrade is not a reason to refuse to boot.
    assert get_settings().port == 9400


def test_a_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv(CONFIG_FILE_VAR, str(tmp_path / "nothing-here.env"))

    assert get_settings().port == 8000


def test_the_path_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv(CONFIG_FILE_VAR, raising=False)
    assert config_file_path() == DEFAULT_CONFIG_FILE

    monkeypatch.setenv(CONFIG_FILE_VAR, r"C:\ProgramData\SysWatch\syswatch.env")
    assert config_file_path() == r"C:\ProgramData\SysWatch\syswatch.env"


def test_the_path_is_read_per_call_not_at_import(config_file, monkeypatch):
    first = config_file("SYSWATCH_PORT=9500\n")
    assert get_settings().port == 9500

    second = first.parent / "other.env"
    second.write_text("SYSWATCH_PORT=9600\n", encoding="utf-8")
    monkeypatch.setenv(CONFIG_FILE_VAR, str(second))

    # Baked into model_config this would still say 9500 — which is what stops a
    # service pointing at a file in its own data directory.
    assert get_settings().port == 9600


def test_a_secret_can_live_in_the_file(config_file):
    config_file("SYSWATCH_SESSION_SECRET=a-secret-that-is-long-enough-to-pass\n")

    assert get_settings().session_secret == "a-secret-that-is-long-enough-to-pass"


# --- the committed example ---------------------------------------------------


def test_the_example_exists_and_is_all_comments():
    lines = [
        line.strip()
        for line in EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    # Every setting is commented out, so copying the file changes nothing by
    # itself — an uncommented SYSWATCH_CORS_ORIGINS= would silently replace the
    # default with an empty list.
    assert lines
    assert all(line.startswith("#") for line in lines)


def test_the_example_carries_no_secret():
    text = EXAMPLE.read_text(encoding="utf-8")

    assert "SYSWATCH_SESSION_SECRET" in text
    assert "token_urlsafe" in text, "should say how to generate one"
    # Nothing that looks like an actual key.
    for line in text.splitlines():
        if "SESSION_SECRET=" in line:
            assert line.strip().endswith("SESSION_SECRET=")


def test_loading_the_example_changes_nothing(tmp_path, monkeypatch):
    copy = tmp_path / "syswatch.env"
    copy.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv(CONFIG_FILE_VAR, str(copy))
    for name in ("SYSWATCH_PORT", "SYSWATCH_AUTH_ENABLED", "SYSWATCH_DEV_MODE"):
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert (settings.port, settings.auth_enabled, settings.dev_mode) == (8000, True, False)
    assert settings.cors_origins == Settings.model_fields["cors_origins"].default
