<#
.SYNOPSIS
    Report what SysWatch needs on this machine, and optionally install it.

.DESCRIPTION
    Install-SysWatch.ps1 refuses to run when a prerequisite is missing, which
    is correct - it should not quietly change a machine in ways nobody asked
    for. This script is the other half: it says what is missing, and installs
    it only when told to.

    It is deliberately separate, and deliberately check-only by default.
    Installing a system-wide language runtime is the operator's decision, not a
    side effect of installing an application: it changes machine PATH and can
    collide with an interpreter already in use.

.PARAMETER Install
    Install what is missing, using winget. Without this the script only
    reports. Needs an administrator prompt.

.PARAMETER IncludeBuildTools
    Also check the compiler, CMake, Ninja and Node. Only needed to build the
    agent and the dashboard from a source checkout - a release archive already
    contains both built.

.EXAMPLE
    .\Install-Prerequisites.ps1
    Report what is present and what is missing. Changes nothing.

.EXAMPLE
    .\Install-Prerequisites.ps1 -Install
    Install the missing runtime prerequisites.

.EXAMPLE
    .\Install-Prerequisites.ps1 -IncludeBuildTools -Install
    The same, plus what is needed to build from source.
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$IncludeBuildTools
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$MinimumPython = [version]'3.10'

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Detail {
    param([string]$Message)
    Write-Host "    $Message"
}

function Write-Warn {
    param([string]$Message)
    Write-Host "    ! $Message" -ForegroundColor Yellow
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-Native {
    <#
        Judged by exit code alone. winget reports progress on stderr, which
        $ErrorActionPreference = 'Stop' would turn into a terminating error
        part-way through installing something.
    #>
    param([string]$Executable, [string[]]$Arguments, [string]$What)

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $Executable @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }

    if ($code -ne 0) {
        foreach ($line in $output) { Write-Host "    $line" -ForegroundColor Red }
        throw "$What failed (exit $code)."
    }
}

function Test-PythonPresent {
    foreach ($candidate in @('python', 'python3', 'py')) {
        if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }

        $reported = $null
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $reported = & $candidate --version 2>&1
            $code = $LASTEXITCODE
        } catch {
            continue
        } finally {
            $ErrorActionPreference = $previous
        }

        if ($code -ne 0) { continue }
        if ($reported -notmatch 'Python (\d+\.\d+\.\d+)') { continue }
        if ([version]$matches[1] -ge $MinimumPython) { return $matches[1] }
    }

    return $null
}

function Test-CommandPresent {
    param([string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return $null
}

# Id is what winget calls it. Required means Install-SysWatch.ps1 will not run
# without it; the rest change what you can do, not whether you can install.
$runtime = @(
    [pscustomobject]@{
        Name = "Python $MinimumPython+"
        Id = 'Python.Python.3.14'
        Required = $true
        Why = 'the backend is a Python application'
        Check = { Test-PythonPresent }
    }
    [pscustomobject]@{
        Name = 'nssm'
        Id = 'NSSM.NSSM'
        Required = $false
        Why = 'runs the backend as a Windows service; without it, start it by hand'
        Check = { Test-CommandPresent 'nssm' }
    }
)

$buildTools = @(
    [pscustomobject]@{
        Name = 'MinGW-w64 (gcc)'
        Id = 'BrechtSanders.WinLibs.POSIX.MSVCRT'
        Required = $false
        Why = 'compiles the agent'
        Check = { Test-CommandPresent 'gcc' }
    }
    [pscustomobject]@{
        Name = 'CMake'
        Id = 'Kitware.CMake'
        Required = $false
        Why = 'configures the agent build'
        Check = { Test-CommandPresent 'cmake' }
    }
    [pscustomobject]@{
        Name = 'Ninja'
        Id = 'Ninja-build.Ninja'
        Required = $false
        Why = 'the generator the agent build uses'
        Check = { Test-CommandPresent 'ninja' }
    }
    [pscustomobject]@{
        Name = 'Node.js 22'
        Id = 'OpenJS.NodeJS'
        Required = $false
        Why = 'builds the dashboard'
        Check = { Test-CommandPresent 'npm' }
    }
)

$wanted = @($runtime)
if ($IncludeBuildTools.IsPresent) { $wanted += $buildTools }

# --- report ------------------------------------------------------------------

Write-Step "Checking prerequisites"

$missing = @()
foreach ($item in $wanted) {
    $found = & $item.Check
    if ($found) {
        Write-Host ("    {0,-9} {1,-18} {2}" -f '[ok]', $item.Name, $found) -ForegroundColor Green
    } else {
        $label = if ($item.Required) { '[MISSING]' } else { '[absent]' }
        $colour = if ($item.Required) { 'Red' } else { 'Yellow' }
        Write-Host ("    {0,-9} {1,-18} {2}" -f $label, $item.Name, $item.Why) -ForegroundColor $colour
        $missing += $item
    }
}

if ($missing.Count -eq 0) {
    Write-Host ""
    Write-Host "Everything is present. Run deploy\Install-SysWatch.ps1 next." -ForegroundColor Green
    Write-Host ""
    exit 0
}

if (-not $IncludeBuildTools.IsPresent) {
    Write-Detail ""
    Write-Detail "Building the agent and dashboard from source needs more:"
    Write-Detail "  .\Install-Prerequisites.ps1 -IncludeBuildTools"
}

# --- install -----------------------------------------------------------------

if (-not $Install.IsPresent) {
    Write-Host ""
    Write-Host "Nothing was changed. To install the above:" -ForegroundColor Cyan
    Write-Host "    .\Install-Prerequisites.ps1 -Install" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Or install them yourself:"
    foreach ($item in $missing) {
        Write-Host "    winget install --id $($item.Id) --exact"
    }
    Write-Host ""
    # Non-zero when something required is still missing, so a script calling
    # this can tell "all present" from "reported and left alone".
    if ($missing | Where-Object { $_.Required }) { exit 1 }
    exit 0
}

if (-not (Test-Administrator)) {
    Write-Host ""
    Write-Host "Installing these needs an elevated prompt." -ForegroundColor Red
    exit 1
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "winget is not available on this machine." -ForegroundColor Red
    Write-Host "It ships with Windows 10 1809 and later as App Installer; update that from"
    Write-Host "the Microsoft Store, or install the packages listed above by hand."
    exit 1
}

Write-Step "Installing"

$failed = @()
foreach ($item in $missing) {
    Write-Detail "$($item.Name) ($($item.Id))"
    try {
        Invoke-Native -Executable 'winget' -Arguments @(
            'install', '--id', $item.Id, '--exact', '--silent',
            '--accept-package-agreements', '--accept-source-agreements',
            # Machine scope, so a service account sees it too. A per-user
            # install would work for the operator and not for LocalSystem.
            '--scope', 'machine'
        ) -What "Installing $($item.Name)"
        Write-Detail "  installed."
    } catch {
        Write-Warn $_.Exception.Message
        $failed += $item
    }
}

Write-Host ""
if ($failed.Count -gt 0) {
    Write-Warn "Some packages did not install. Try them by hand:"
    foreach ($item in $failed) {
        Write-Warn "  winget install --id $($item.Id) --exact"
    }
    exit 1
}

Write-Host "Prerequisites installed." -ForegroundColor Green
Write-Host ""
# The reason this is not folded into Install-SysWatch.ps1: a process cannot see
# a PATH change made after it started, so the installer would still not find
# what was just installed for it.
Write-Host "Open a NEW elevated prompt before running Install-SysWatch.ps1 -" -ForegroundColor Yellow
Write-Host "this one cannot see the PATH these packages just added." -ForegroundColor Yellow
Write-Host ""
