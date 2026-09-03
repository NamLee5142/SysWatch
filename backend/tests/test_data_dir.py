"""Where the database and logs live.

Before this, the default database path was relative to the working directory.
A Windows Service starts in C:\\Windows\\System32, so that default either failed
on permissions or left a database somewhere nobody thinks to look.
"""
import logging
from pathlib import Path

import pytest

from app.main import warn_about_a_stray_database
from config import DATA_DIR_VAR, Settings, default_data_dir, ensure_data_dir


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (DATA_DIR_VAR, "SYSWATCH_DATABASE_URL", "SYSWATCH_LOG_DIR", "SYSWATCH_DEV_MODE"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# --- the default ------------------------------------------------------------


def test_windows_defaults_to_program_data(clean_env):
    clean_env.setenv("PROGRAMDATA", r"C:\ProgramData")

    # Only meaningful on Windows; elsewhere the relative default is correct.
    expected = r"C:\ProgramData\SysWatch" if Path().absolute().drive else "data"
    assert default_data_dir() == expected


def test_development_keeps_its_data_beside_the_checkout():
    # Scattering a laptop's test data through ProgramData helps no one.
    assert default_data_dir(dev_mode=True) == "data"


def test_dev_mode_moves_the_whole_installation(clean_env):
    clean_env.setenv("SYSWATCH_DEV_MODE", "true")

    settings = Settings()

    assert settings.data_dir == "data"
    assert settings.database_url == "sqlite:///data/syswatch.db"


# --- derivation -------------------------------------------------------------


def test_naming_one_directory_moves_everything(clean_env, tmp_path):
    clean_env.setenv(DATA_DIR_VAR, str(tmp_path))

    settings = Settings()

    # What someone relocating an installation means by it.
    assert settings.database_url == f"sqlite:///{tmp_path.as_posix()}/syswatch.db"
    assert settings.log_dir == str(tmp_path / "logs")


def test_the_database_url_uses_forward_slashes(clean_env):
    clean_env.setenv(DATA_DIR_VAR, r"D:\SysWatch Data")

    # A Windows path in a sqlite:/// URL has to use forward slashes, or
    # SQLAlchemy reads the backslashes as escapes.
    assert "\\" not in Settings().database_url
    assert Settings().database_url == "sqlite:///D:/SysWatch Data/syswatch.db"


def test_an_explicit_database_url_is_left_alone(clean_env, tmp_path):
    clean_env.setenv(DATA_DIR_VAR, str(tmp_path))
    clean_env.setenv("SYSWATCH_DATABASE_URL", "postgresql://elsewhere/syswatch")

    settings = Settings()

    assert settings.database_url == "postgresql://elsewhere/syswatch"
    # The log directory still follows the data directory.
    assert settings.log_dir == str(tmp_path / "logs")


def test_an_explicit_log_dir_is_left_alone(clean_env, tmp_path):
    clean_env.setenv(DATA_DIR_VAR, str(tmp_path))
    clean_env.setenv("SYSWATCH_LOG_DIR", r"D:\logs\syswatch")

    assert Settings().log_dir == r"D:\logs\syswatch"


# --- creating it ------------------------------------------------------------


def test_the_directory_is_created(clean_env, tmp_path):
    target = tmp_path / "nested" / "SysWatch"
    clean_env.setenv(DATA_DIR_VAR, str(target))

    ensure_data_dir(Settings())

    assert target.is_dir()


def test_creating_it_twice_is_fine(clean_env, tmp_path):
    clean_env.setenv(DATA_DIR_VAR, str(tmp_path / "d"))

    ensure_data_dir(Settings())
    ensure_data_dir(Settings())


# --- the upgrade someone is about to be surprised by -------------------------


def test_a_database_left_in_the_working_directory_is_reported(clean_env, tmp_path, monkeypatch, caplog):
    working = tmp_path / "checkout"
    working.mkdir()
    (working / "syswatch.db").write_text("not really a database", encoding="utf-8")
    monkeypatch.chdir(working)
    clean_env.setenv(DATA_DIR_VAR, str(tmp_path / "ProgramData"))

    with caplog.at_level(logging.WARNING):
        warn_about_a_stray_database(Settings(), logging.getLogger("test"))

    # Otherwise an upgrade silently starts from an empty database and there is
    # nothing to say where the history went.
    assert "Earlier versions defaulted to the working directory" in caplog.text


def test_nothing_is_said_when_there_is_no_stray_database(clean_env, tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    clean_env.setenv(DATA_DIR_VAR, str(tmp_path / "data"))

    with caplog.at_level(logging.WARNING):
        warn_about_a_stray_database(Settings(), logging.getLogger("test"))

    assert caplog.text == ""


def test_nothing_is_said_when_that_is_the_configured_database(clean_env, tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "syswatch.db").write_text("x", encoding="utf-8")
    clean_env.setenv(DATA_DIR_VAR, str(tmp_path))

    with caplog.at_level(logging.WARNING):
        warn_about_a_stray_database(Settings(), logging.getLogger("test"))

    # It is the one in use; there is nothing to warn about.
    assert caplog.text == ""
