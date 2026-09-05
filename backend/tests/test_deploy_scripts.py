"""Guards on the deployment scripts that Python can check without running them.

The installer only ever runs on a machine somebody is deploying to, which is
the worst place to discover that it does not parse. These are the two failures
that are invisible in review and fatal in the field.
"""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "deploy"

SCRIPTS = sorted(DEPLOY.glob("*.ps1"))


def test_there_are_deployment_scripts():
    assert [path.name for path in SCRIPTS] == [
        "Install-Prerequisites.ps1",
        "Install-SysWatch.ps1",
        "Uninstall-SysWatch.ps1",
    ]


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.name)
def test_the_script_is_ascii_only(script):
    r"""Non-ASCII in a BOM-less script is a syntax error waiting on a machine.

    Windows PowerShell 5.1 reads a file without a BOM as the system codepage,
    not as UTF-8. An em dash is three UTF-8 bytes, and the last of them is 0x94
    - which in CP1252 is a right double quotation mark, a character PowerShell
    treats as a string delimiter. One dash in a comment therefore unbalances
    the quoting for the rest of the file, and the parse error surfaces hundreds
    of lines away with nothing to connect it back.

    A BOM would also fix it. ASCII is chosen instead because it survives being
    re-saved by an editor, a copy through a pipeline, or a paste into a console.
    """
    text = script.read_text(encoding="utf-8")

    offenders = [
        (number, character)
        for number, line in enumerate(text.splitlines(), 1)
        for character in line
        if ord(character) > 127
    ]

    assert offenders == [], "\n".join(
        f"line {number}: {character!r} (U+{ord(character):04X})"
        for number, character in offenders
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.name)
def test_native_commands_are_not_left_to_stderr(script):
    """$ErrorActionPreference = 'Stop' turns native stderr into a failure.

    pip warns to stderr routinely and `python -m venv` reports a redirected
    path the same way, so a bare `& $python ...` aborts an install over output
    that was not a failure at all. Install-SysWatch routes those through
    Invoke-Native, which judges the exit code instead.
    """
    text = script.read_text(encoding="utf-8")

    if "Invoke-Native" not in text:
        pytest.skip("no long-running native commands in this script")

    assert "$ErrorActionPreference = 'Continue'" in text


def test_removing_data_needs_an_exact_confirmation():
    r"""The uninstaller must not accept a lowercase "delete".

    `-cne` is a case-sensitive comparison. Softened to `-ne`, someone typing
    "delete" at the prompt destroys every snapshot, alert and account, which is
    the one action in either script that cannot be undone.
    """
    text = (DEPLOY / "Uninstall-SysWatch.ps1").read_text(encoding="utf-8")

    assert "-cne 'DELETE'" in text, "the confirmation is no longer case-sensitive"


def test_the_data_directory_is_kept_unless_asked_for():
    """An uninstall is not the moment to decide history is disposable."""
    text = (DEPLOY / "Uninstall-SysWatch.ps1").read_text(encoding="utf-8")

    # The only Remove-Item that touches the data directory sits behind the
    # -RemoveData switch; the default path prints what it kept.
    assert "if (-not $RemoveData.IsPresent) {" in text
    assert 'Write-Step "Keeping $DataDir"' in text


def test_nssm_is_never_called_bare():
    r"""nssm reports what it did on stderr.

    With $ErrorActionPreference = 'Stop', a bare `& nssm ...` turns that into a
    terminating error and aborts an install over a message that was not a
    failure. Both scripts must neutralise that: the installer routes nssm
    through Invoke-Native, the uninstaller sets 'Continue' around its one call.
    """
    installer = (DEPLOY / "Install-SysWatch.ps1").read_text(encoding="utf-8")
    uninstaller = (DEPLOY / "Uninstall-SysWatch.ps1").read_text(encoding="utf-8")

    for line in installer.splitlines():
        stripped = line.strip()
        if stripped.startswith("& $nssm"):
            pytest.fail(f"bare nssm call in the installer: {stripped}")

    assert "$ErrorActionPreference = 'Continue'" in uninstaller


def test_the_backend_service_is_launched_with_a_path_that_has_no_space():
    r"""nssm splits AppParameters on spaces before handing them to the process.

    The default install root is "C:\Program Files\SysWatch", so an absolute
    script path arrives at Python as `C:\Program` and the service fails to
    start on every default installation:

        python.exe: can't open file 'C:\Program': [Errno 2] No such file

    AppDirectory is already the backend directory, so the parameter is a bare
    filename with no space in it and nothing to quote.
    """
    text = (DEPLOY / "Install-SysWatch.ps1").read_text(encoding="utf-8")

    assert "'AppParameters', 'serve.py'" in text

    # And nothing hands nssm an absolute path as an argument either.
    for line in text.splitlines():
        stripped = line.strip()
        if "AppParameters" in stripped and "$serveScript" in stripped:
            pytest.fail(f"AppParameters gets an absolute path: {stripped}")


def test_the_prerequisites_script_changes_nothing_by_default():
    """Reporting is safe; installing a system runtime is a decision."""
    prerequisites = (DEPLOY / "Install-Prerequisites.ps1").read_text(encoding="utf-8")

    assert "[switch]$Install" in prerequisites
    assert "if (-not $Install.IsPresent) {" in prerequisites


def test_installing_a_prerequisite_is_offered_and_never_assumed():
    """The installer may offer, but the default answer is no.

    Installing a system-wide language runtime changes machine PATH and can
    collide with an interpreter already in use, so it is a question rather
    than a side effect - and -InstallPrerequisites is how an unattended run
    answers it in advance.
    """
    installer = (DEPLOY / "Install-SysWatch.ps1").read_text(encoding="utf-8")

    assert "[switch]$InstallPrerequisites" in installer
    assert "if ($InstallPrerequisites.IsPresent) { return $true }" in installer
    assert 'Read-Host "    Install it? [y/N]"' in installer


def test_the_prompt_is_skipped_when_nobody_is_at_the_keyboard():
    """A prompt in a deployment pipeline is a hang, not a question."""
    installer = (DEPLOY / "Install-SysWatch.ps1").read_text(encoding="utf-8")

    assert "if (-not [Environment]::UserInteractive) { return $false }" in installer
    assert "if ([Console]::IsInputRedirected) { return $false }" in installer


def test_a_newly_installed_prerequisite_is_looked_for_again():
    """A process keeps the environment it was launched with.

    winget writes the new PATH entry to the registry, so without re-reading it
    the installer would install Python and then still not find it.
    """
    installer = (DEPLOY / "Install-SysWatch.ps1").read_text(encoding="utf-8")

    assert "function Update-PathFromRegistry" in installer
    assert "[Environment]::GetEnvironmentVariable('PATH', 'Machine')" in installer

    # And the refresh is followed by looking again, not just called and
    # forgotten - refreshing PATH without re-checking would change nothing.
    stripped = [line.strip() for line in installer.splitlines()]
    refresh = stripped.index("Update-PathFromRegistry")
    assert "Get-PythonCommand" in stripped[refresh + 1]


def test_prerequisites_are_installed_for_the_machine_not_the_user():
    """A per-user install is invisible to LocalSystem.

    Both services run as LocalSystem. Python installed only for the operator
    would satisfy the installer's check and then not exist for the service
    that has to run it.
    """
    text = (DEPLOY / "Install-Prerequisites.ps1").read_text(encoding="utf-8")

    assert "'--scope', 'machine'" in text
