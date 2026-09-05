import json
import sys
from pathlib import Path

import pytest

from app.version import UNKNOWN, VERSION, read_version

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import sync_version  # noqa: E402  - needs the path above


def test_the_backend_reports_the_version_in_the_version_file():
    assert VERSION == (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_the_version_is_semver():
    assert sync_version.SEMVER.match(VERSION)


def test_every_component_agrees_with_the_version_file():
    """The point of a single source: nothing may quietly hold a second copy.

    Fails when VERSION has been bumped without running the sync script, which
    is the moment it would otherwise go unnoticed — the dashboard would report
    one version and the backend another.
    """
    problems = sync_version.drift(sync_version.read_version())

    assert problems == [], "\n".join(problems + ["Run: python scripts/sync_version.py"])


def test_cmake_reads_the_version_file_rather_than_declaring_one():
    cmake = (REPO_ROOT / "agent" / "CMakeLists.txt").read_text(encoding="utf-8")

    assert 'file(READ "${CMAKE_CURRENT_SOURCE_DIR}/../VERSION" SYSWATCH_VERSION)' in cmake
    # A literal here would be a fourth copy, and the one nobody thinks to check.
    assert "project(agent VERSION ${SYSWATCH_VERSION}" in cmake


def test_health_reports_the_version(anon_client):
    body = anon_client.get("/health").json()

    assert body["status"] == "ok"
    assert body["version"] == VERSION


def test_health_needs_no_session(anon_client):
    """A deployment check runs before anyone has logged in."""
    response = anon_client.get("/health")

    assert response.status_code == 200


def test_an_environment_override_wins(tmp_path):
    file = tmp_path / "VERSION"
    file.write_text("1.2.3\n", encoding="utf-8")

    found = read_version(candidates=(file,), environ={"SYSWATCH_VERSION": "9.9.9"})

    assert found == "9.9.9"


def test_a_blank_override_is_ignored(tmp_path):
    file = tmp_path / "VERSION"
    file.write_text("1.2.3\n", encoding="utf-8")

    assert read_version(candidates=(file,), environ={"SYSWATCH_VERSION": "  "}) == "1.2.3"


def test_a_missing_version_file_does_not_stop_the_process(tmp_path):
    """A packaging mistake should show up in /health, not as a failure to boot."""
    assert read_version(candidates=(tmp_path / "absent",), environ={}) == UNKNOWN


def test_an_empty_version_file_falls_through_to_the_next_candidate(tmp_path):
    empty = tmp_path / "empty"
    empty.write_text("   \n", encoding="utf-8")
    real = tmp_path / "real"
    real.write_text("2.0.0\n", encoding="utf-8")

    assert read_version(candidates=(empty, real), environ={}) == "2.0.0"


def test_a_directory_where_the_file_should_be_is_survived(tmp_path):
    directory = tmp_path / "VERSION"
    directory.mkdir()

    assert read_version(candidates=(directory,), environ={}) == UNKNOWN


def test_sync_rejects_a_version_that_cmake_would_not_accept(tmp_path):
    file = tmp_path / "VERSION"
    file.write_text("0.10\n", encoding="utf-8")

    with pytest.raises(sync_version.VersionProblem, match="MAJOR.MINOR.PATCH"):
        sync_version.read_version(file)


def test_sync_updates_both_version_fields_in_a_lockfile(tmp_path):
    """npm states the root package's version twice; one of them is easy to miss."""
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(
        json.dumps(
            {
                "name": "dashboard",
                "version": "0.0.0",
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "dashboard", "version": "0.0.0"},
                    "node_modules/x": {"version": "1.0.0"},
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    assert sync_version.write_versions(lockfile, "3.4.5")

    document = json.loads(lockfile.read_text(encoding="utf-8"))
    assert document["version"] == "3.4.5"
    assert document["packages"][""]["version"] == "3.4.5"
    # A dependency's version is not ours to rewrite.
    assert document["packages"]["node_modules/x"]["version"] == "1.0.0"


def test_sync_is_idempotent(tmp_path):
    package = tmp_path / "package.json"
    package.write_text('{\n  "version": "3.4.5"\n}\n', encoding="utf-8")

    assert sync_version.write_versions(package, "3.4.5") is False


def test_sync_leaves_the_rest_of_the_file_byte_for_byte(tmp_path):
    package = tmp_path / "package.json"
    original = '{\n  "name": "dashboard",\n  "version": "0.0.0",\n  "private": true\n}\n'
    package.write_text(original, encoding="utf-8")

    sync_version.write_versions(package, "3.4.5")

    assert package.read_text(encoding="utf-8") == original.replace("0.0.0", "3.4.5")


def test_drift_reports_the_field_that_disagrees(tmp_path):
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "package.json").write_text('{"version": "0.0.1"}', encoding="utf-8")

    problems = sync_version.drift("9.9.9", repo_root=tmp_path)

    assert len(problems) == 1
    assert "0.0.1" in problems[0] and "9.9.9" in problems[0]
