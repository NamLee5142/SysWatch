<#
.SYNOPSIS
    Stop and remove SysWatch from this machine.

.DESCRIPTION
    Stops and deregisters the services, removes the installed program files and
    clears the machine environment variable.

    The data directory is left alone. It holds the database - every snapshot,
    every alert, every account - and an uninstall is not the moment to decide
    that history is disposable. Pass -RemoveData to delete it, which prompts
    unless -Force is given as well.

.PARAMETER InstallRoot
    Where the program files are. Default: C:\Program Files\SysWatch

.PARAMETER DataDir
    Where the database, logs and configuration live. Default:
    C:\ProgramData\SysWatch. Kept unless -RemoveData.

.PARAMETER RemoveData
    Also delete the data directory. Irreversible.

.PARAMETER Force
    Do not prompt before deleting the data directory.

.EXAMPLE
    .\Uninstall-SysWatch.ps1

.EXAMPLE
    .\Uninstall-SysWatch.ps1 -RemoveData
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = "$env:ProgramFiles\SysWatch",
    [string]$DataDir = "$env:ProgramData\SysWatch",
    [switch]$RemoveData,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$AgentServiceName = 'SysWatchAgent'
$BackendServiceName = 'SysWatchBackend'

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

if (-not (Test-Administrator)) {
    Write-Host "Removing a service needs an elevated prompt." -ForegroundColor Red
    exit 1
}

# --- services ----------------------------------------------------------------

Write-Step "Stopping services"

foreach ($name in @($BackendServiceName, $AgentServiceName)) {
    $service = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $service) {
        Write-Detail "$name is not registered."
        continue
    }

    if ($service.Status -ne 'Stopped') {
        try {
            Stop-Service -Name $name -Force
            Write-Detail "Stopped $name."
        } catch {
            Write-Warn "Could not stop ${name}: $($_.Exception.Message)"
        }
    }
}

Write-Step "Removing services"

# The agent removes its own registration, so the uninstall path is the one the
# agent defines rather than a second implementation of it here.
$agentBinary = Join-Path $InstallRoot 'agent\agent.exe'
if (Test-Path -LiteralPath $agentBinary) {
    & $agentBinary --uninstall
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "agent.exe --uninstall exited $LASTEXITCODE; falling back to sc.exe."
        & sc.exe delete $AgentServiceName | Out-Null
    } else {
        Write-Detail "$AgentServiceName removed."
    }
} elseif (Get-Service -Name $AgentServiceName -ErrorAction SilentlyContinue) {
    # The binary is gone but the registration is not, which is what a partly
    # finished uninstall looks like.
    & sc.exe delete $AgentServiceName | Out-Null
    Write-Detail "$AgentServiceName removed with sc.exe."
}

if (Get-Service -Name $BackendServiceName -ErrorAction SilentlyContinue) {
    # nssm writes what it did to stderr, which $ErrorActionPreference = 'Stop'
    # turns into a terminating error - so an uninstall would abort partway,
    # having stopped the services and removed nothing.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $nssm = Get-Command nssm -ErrorAction SilentlyContinue
        if ($nssm) {
            & $nssm.Source remove $BackendServiceName confirm 2>&1 | Out-Null
        } else {
            # nssm removed after the service was registered with it. The
            # registration is an ordinary service entry either way.
            & sc.exe delete $BackendServiceName 2>&1 | Out-Null
        }
    } finally {
        $ErrorActionPreference = $previous
    }

    if (Get-Service -Name $BackendServiceName -ErrorAction SilentlyContinue) {
        Write-Warn "$BackendServiceName is still registered. It may be marked for deletion until the process exits."
    } else {
        Write-Detail "$BackendServiceName removed."
    }
}

# --- files -------------------------------------------------------------------

Write-Step "Removing $InstallRoot"

if (Test-Path -LiteralPath $InstallRoot) {
    try {
        Remove-Item -LiteralPath $InstallRoot -Recurse -Force
        Write-Detail "Removed."
    } catch {
        # Usually a file still open by a service that has not finished exiting.
        Write-Warn "Could not remove everything: $($_.Exception.Message)"
        Write-Warn "Something may still be running. Try again in a moment."
    }
} else {
    Write-Detail "Nothing installed there."
}

[Environment]::SetEnvironmentVariable('SYSWATCH_CONFIG_FILE', $null, 'Machine')
Write-Detail "Cleared SYSWATCH_CONFIG_FILE."

[Environment]::SetEnvironmentVariable('SYSWATCH_AGENT_CONFIG_FILE', $null, 'Machine')
Write-Detail "Cleared SYSWATCH_AGENT_CONFIG_FILE."

# --- data --------------------------------------------------------------------

if (-not $RemoveData.IsPresent) {
    Write-Step "Keeping $DataDir"
    Write-Detail "The database, logs and configuration are still there."
    Write-Detail "Delete them with: .\Uninstall-SysWatch.ps1 -RemoveData"
} elseif (-not (Test-Path -LiteralPath $DataDir)) {
    Write-Step "No data directory at $DataDir"
} else {
    Write-Step "Removing $DataDir"

    if (-not $Force.IsPresent) {
        Write-Host ""
        Write-Host "    This deletes every snapshot, alert and account in $DataDir." -ForegroundColor Yellow
        $answer = Read-Host "    Type the word DELETE to confirm"
        if ($answer -cne 'DELETE') {
            Write-Detail "Left alone."
            Write-Host ""
            Write-Host "SysWatch is uninstalled. The data directory was kept." -ForegroundColor Green
            exit 0
        }
    }

    Remove-Item -LiteralPath $DataDir -Recurse -Force
    Write-Detail "Removed."
}

Write-Host ""
Write-Host "SysWatch is uninstalled." -ForegroundColor Green
Write-Host ""
