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
