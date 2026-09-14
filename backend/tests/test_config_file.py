"""Reading settings from a file.

A Windows Service has no shell to export from, so a secret has to live
somewhere it can be read at startup — while an operator overriding one value
for one run should not have to edit that file.
"""
from pathlib import Path

import re

import pytest

from config import (
    CONFIG_FILE_NAME,
    CONFIG_FILE_VAR,
    DATA_DIR_VAR,
    Settings,
    config_file_path,
    get_settings,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = BACKEND_ROOT / "syswatch.env.example"
README = BACKEND_ROOT / "README.md"


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
    monkeypatch.delenv(DATA_DIR_VAR, raising=False)
    assert config_file_path() == CONFIG_FILE_NAME

    monkeypatch.setenv(CONFIG_FILE_VAR, r"C:\ProgramData\SysWatch\syswatch.env")
    assert config_file_path() == r"C:\ProgramData\SysWatch\syswatch.env"


def test_the_data_directory_supplies_the_path_when_nothing_else_does(monkeypatch, tmp_path):
    monkeypatch.delenv(CONFIG_FILE_VAR, raising=False)
    monkeypatch.setenv(DATA_DIR_VAR, str(tmp_path))

    # Naming one directory should be enough to move the whole installation.
    assert config_file_path() == str(tmp_path / CONFIG_FILE_NAME)


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


@pytest.mark.parametrize("field", sorted(Settings.model_fields))
def test_every_setting_appears_in_the_example(field):
    """The installer ships this file as the machine's configuration.

    A setting documented only in README.md is a setting an operator never finds:
    they open syswatch.env, not the repository. Sprint 11 added nine
    notification settings, documented them in two READMEs, and left this file
    describing a version of the application that could not send an alert - which
    no other test noticed, because the ones above only check that the file is
    all comments and carries no secret.

    Parametrized rather than a set comparison so the failure names the setting
    that is missing instead of printing a diff of twenty-six.
    """
    name = f"SYSWATCH_{field.upper()}"

    assert name in EXAMPLE.read_text(encoding="utf-8"), (
        f"{name} is not in syswatch.env.example. Add it, commented out, in the "
        "section it belongs to."
    )


# The agent reads this same file, and its settings are not in Settings - they
# are recognised by name in the agent's C++ config loader. Read from there so
# the two cannot drift: a key added to the loader and not to the example fails
# here, which is the hole the backend-only version of this test left open when
# the agent started sharing the file.
AGENT_LOADER = (
    BACKEND_ROOT.parent / "agent" / "src" / "config" / "ConfigFile.cpp"
)


def agent_keys():
    source = AGENT_LOADER.read_text(encoding="utf-8")
    return sorted(set(re.findall(r'key == "(SYSWATCH_AGENT_[A-Z0-9_]+)"', source)))


def test_the_agent_loader_is_where_it_is_expected():
    """A moved file would make agent_keys() return nothing, silently."""
    assert AGENT_LOADER.is_file()
    assert len(agent_keys()) >= 5


@pytest.mark.parametrize("name", agent_keys())
def test_every_agent_setting_appears_in_the_example(name):
    """The agent's keys, in the file the agent reads.

    Sprint 12 added eight of these and documented none of them, which is the
    same gap that nearly shipped in v0.11.0 - a config template that does not
    describe the release's feature. The backend-only version of this test could
    not see them, because they are not Settings fields.
    """
    assert name in EXAMPLE.read_text(encoding="utf-8"), (
        f"{name} is read by the agent but is not in syswatch.env.example."
    )


@pytest.mark.parametrize("name", agent_keys())
def test_every_agent_setting_appears_in_the_backend_readme(name):
    """The same drift, one document over.

    README.md carries its own table of these, because "adding a second machine
    needs no reading of source" was the point of documenting them at all. A
    second copy is a second thing to forget, and this file's own history is the
    argument: the settings were added, documented in two READMEs, and left out
    of the template until a test went looking.
    """
    assert name in README.read_text(encoding="utf-8"), (
        f"{name} is read by the agent but is not in backend/README.md. "
        "It is documented where an operator will not look for it."
    )


def test_the_example_invents_no_settings():
    """The other direction: a name here that config.py does not read.

    A typo, or a setting that was renamed and left behind. Either way an
    operator sets it and nothing happens.
    """
    known = {f"SYSWATCH_{field.upper()}" for field in Settings.model_fields}
    # The agent's keys are read by agent/src/config/ConfigFile.cpp, not by
    # Settings, and belong in this file just as much.
    known |= set(agent_keys())
    # The variable that names this file is read before Settings exists, so it is
    # not a field, and it is the one name legitimately here that config.py does
    # not declare.
    known.add(CONFIG_FILE_VAR)

    found = set(
        re.findall(r"^#?(SYSWATCH_[A-Z0-9_]+)=", EXAMPLE.read_text(encoding="utf-8"), re.M)
    )

    assert found <= known, f"not read by config.py: {sorted(found - known)}"


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
