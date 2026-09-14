"""What CI is triggered by.

Trigger configuration has no tests of its own anywhere else, and it is the
kind of thing that is edited to fix one symptom and quietly re-broken later.
"""
import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# Workflows that gate a change: they run the tests a reviewer reads before
# merging. release.yml is not one of them - it is driven by a tag.
SUITES = ("agent.yml", "backend.yml", "dashboard.yml", "install.yml")


def triggers(name):
    """The `on:` block. YAML reads a bare `on` as the boolean True."""
    loaded = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return loaded[True] if True in loaded else loaded["on"]


@pytest.fixture(params=SUITES)
def suite(request):
    return request.param


def test_the_workflows_are_all_present():
    found = {path.name for path in WORKFLOWS.glob("*.yml")}

    assert set(SUITES) <= found


def test_a_suite_runs_on_pull_requests(suite):
    """The run that gates a merge."""
    assert "pull_request" in triggers(suite)


def test_a_suite_does_not_also_run_on_every_branch_push(suite):
    """The duplication this file exists to prevent.

    A branch with an open pull request raises both events for the same commit.
    Running on both meant two identical runs, two green ticks and twice the
    minutes, with no more confidence than one of them gave.
    """
    push = triggers(suite).get("push")
    if push is None:
        return  # install.yml: pull requests only, which is the same answer

    assert push.get("branches") == ["main"], (
        f"{suite} runs on pushes to {push.get('branches')}, "
        "which duplicates its own pull_request run"
    )


def test_a_suite_can_be_run_by_hand(suite):
    """The escape hatch that makes the narrowing affordable.

    Without this, a branch with no pull request open has no way to reach CI
    short of opening one.
    """
    assert "workflow_dispatch" in triggers(suite)


def test_pull_requests_are_not_filtered_by_path(suite):
    """A required check that never runs is not skipped - it stays pending.

    A documentation-only pull request would be unmergeable the moment these
    become required checks, so the pull_request trigger deliberately has no
    paths filter even though the push trigger does.
    """
    pull_request = triggers(suite)["pull_request"]

    assert pull_request is None or "paths" not in pull_request


def test_the_release_workflow_is_driven_by_a_tag():
    """Not by a branch: a release is cut from something already merged."""
    on = triggers("release.yml")

    assert on["push"]["tags"] == ["v*"]
    assert "pull_request" not in on


def test_the_install_workflow_covers_both_kinds_of_install():
    """The plain install is not the one that breaks in the field.

    Sprint 12 gave the installer a second mode - an agent configured to push to
    a backend elsewhere - and for most of the sprint CI exercised only the
    first. A pushing install has more to go wrong than a plain one and less to
    notice it: it succeeds, the services run, and the only symptom of a mistake
    is a host that never appears somewhere else.

    This checks that the coverage exists, not that it passes; only the run
    itself can say that. It is here so that deleting the steps is a decision
    rather than an edit.
    """
    text = (WORKFLOWS / "install.yml").read_text(encoding="utf-8")

    plain = re.search(r"Install-SysWatch\.ps1 -SkipAdminAccount\s*$", text, re.M)
    assert plain, "install.yml no longer covers the single-machine install"

    assert "-BackendUrl" in text, (
        "install.yml no longer installs an agent that pushes"
    )
    assert "create_agent_token" in text, (
        "the workflow's token must come from the shipped command, so that a "
        "change to how tokens are issued breaks this rather than passing on a "
        "fixture the product does not use"
    )


def test_a_release_is_titled_with_its_tag_alone():
    """"v0.12.0", not "SysWatch 0.12.0".

    Every release from v0.10.0 on is named with the bare tag. The workflow used
    to title them "SysWatch <version>", so each one had to be renamed by hand
    after it published - a step that is easy to forget and invisible in review.
    """
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")

    titles = re.findall(r"--title\s+(\S+)", release)

    assert titles == ['"${GITHUB_REF_NAME}"'], f"release title is {titles}"


def test_the_release_notes_do_not_outlive_the_installer_they_describe():
    """The notes are written into every release, so they must stay true.

    They tell an operator to pass -AllowInsecurePush to reach a second machine.
    Sprint 13 removes that parameter once the agent speaks TLS, and a release
    whose notes name a flag the installer refuses would send somebody hunting a
    typo. This fails on the commit that removes it, which is when the paragraph
    needs rewriting.
    """
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    installer = (WORKFLOWS.parents[1] / "deploy" / "Install-SysWatch.ps1").read_text(
        encoding="utf-8"
    )

    for parameter in ("-BackendUrl", "-AgentToken", "-AllowInsecurePush"):
        if parameter in release:
            assert f"${parameter[1:]}" in installer, (
                f"release.yml tells operators to use {parameter}, "
                "which Install-SysWatch.ps1 no longer accepts"
            )
