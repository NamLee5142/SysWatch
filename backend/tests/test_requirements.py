"""What a deployment installs, and what it must not.

deploy/Install-SysWatch.ps1 builds the production virtual environment from
requirements.txt. Every line in that file is therefore installed on every
monitored machine, whether the machine has any use for it or not.
"""
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
PRODUCTION = BACKEND / "requirements.txt"
DEVELOPMENT = BACKEND / "requirements-dev.txt"

# Not a general "is this a test package" rule, which would be a guess. These
# are the ones this project uses, and the list grows when the suite gains a
# dependency rather than when someone remembers to look.
TEST_ONLY = {"pytest", "respx", "psycopg", "coverage", "hypothesis", "faker"}


def requirements(path):
    """Package names, lowercased, ignoring comments, blanks and -r includes."""
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        name = line.split("==")[0].split(">")[0].split("[")[0].strip()
        names.append(name.lower())
    return names


def test_both_files_exist():
    assert PRODUCTION.is_file()
    assert DEVELOPMENT.is_file()


@pytest.mark.parametrize("package", sorted(TEST_ONLY))
def test_production_installs_no_test_framework(package):
    """The point of the split.

    A test framework on a production machine is not dangerous, it is just
    untrue: it says the machine runs tests, and it gives an attacker who
    reaches the virtual environment more code than the application needs.
    """
    assert package not in requirements(PRODUCTION)


def test_the_development_file_includes_the_production_one():
    """So `pip install -r requirements-dev.txt` is the whole answer.

    Two separate installs is a step someone eventually skips.
    """
    content = DEVELOPMENT.read_text(encoding="utf-8")

    assert "-r requirements.txt" in content


def test_the_suite_can_still_be_installed():
    """Whatever the suite imports has to be declared somewhere.

    pytest and respx are the two third-party packages the tests use that the
    application does not; if either left the development file, CI would only
    discover it on a clean runner.
    """
    declared = set(requirements(PRODUCTION)) | set(requirements(DEVELOPMENT))

    assert {"pytest", "respx"} <= declared


def test_every_pin_is_exact():
    """A range is a build that differs from the one that was tested.

    The installer runs pip on a machine nobody is watching, months after the
    release was cut.
    """
    for path in (PRODUCTION, DEVELOPMENT):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if not line or line.startswith("-"):
                continue
            assert "==" in line, f"{path.name}: {line!r} is not pinned"
