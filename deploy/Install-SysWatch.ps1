<#
.SYNOPSIS
    Install or upgrade SysWatch on this machine.

.DESCRIPTION
    Copies the agent, the backend and the built dashboard into an install
    directory, prepares the data directory, migrates the database, creates the
    first account and registers the services.

    Running it a second time over an existing install is an upgrade. Two things
    are load-bearing there and are treated as such:

      * The session secret is generated once and never regenerated. It is the
        HMAC key for every session token, so replacing it signs everybody out -
        a thing that would otherwise happen quietly on every deploy.
      * The database is backed up before migrating, using the same VACUUM INTO
        backup the operator would take by hand.

    The data directory is never deleted by this script.

.PARAMETER InstallRoot
    Where the program files go. Default: C:\Program Files\SysWatch

.PARAMETER DataDir
    Where the database, logs and configuration live. Default:
    C:\ProgramData\SysWatch. Survives upgrades.

.PARAMETER Port
    Port for the backend. Default: 8000

.PARAMETER SkipServices
    Install the files, configuration and schema, but register nothing with the
    Service Control Manager and set no machine environment variable. Needs no
    administrator rights. Use it to stage an install, or to check what the
    script does before letting it touch the machine.

.PARAMETER SkipAdminAccount
    Do not prompt for the first account. The backend will start and refuse
    every login until one exists; create it with:
        python -m app.auth.create_admin

.EXAMPLE
    .\Install-SysWatch.ps1

.EXAMPLE
    .\Install-SysWatch.ps1 -InstallRoot D:\SysWatch -Port 9000
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = "$env:ProgramFiles\SysWatch",
    [string]$DataDir = "$env:ProgramData\SysWatch",
    [int]$Port = 8000,
    [string]$SourceRoot,
    [switch]$SkipServices,
    [switch]$SkipAdminAccount
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$AgentServiceName = 'SysWatchAgent'
$BackendServiceName = 'SysWatchBackend'
$ConfigFileName = 'syswatch.env'
$MinimumPython = [version]'3.10'

if (-not $SourceRoot) {
    $SourceRoot = Split-Path -Parent $PSScriptRoot
}

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

function Get-PythonCommand {
    <#
        The interpreter used to build the install's virtual environment. Found
        rather than assumed, because "python" on PATH is a Store alias on some
        machines that opens a shop instead of running anything.
    #>
    foreach ($candidate in @('python', 'python3', 'py')) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $command) { continue }

        # The Store stub writes to stderr, which is a terminating error here
        # while $ErrorActionPreference is Stop - so a machine with the alias
        # installed would stop the script rather than move on to the next
        # candidate, which is the whole point of the loop.
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

        $found = [version]$matches[1]
        if ($found -ge $MinimumPython) {
            return [pscustomobject]@{ Command = $candidate; Version = $found }
        }
    }

    return $null
}

function New-SessionSecret {
    <#
        48 bytes, URL-safe, matching what syswatch.env.example tells an
        operator to generate with secrets.token_urlsafe(48). Generated here so
        an install does not depend on an interpreter being importable yet.
    #>
    $bytes = New-Object byte[] 48
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    } finally {
        $generator.Dispose()
    }

    return [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_').TrimEnd('=')
}

function Get-ExistingSessionSecret {
    <#
        The secret already in use, or $null.

        Only an uncommented assignment counts. syswatch.env.example ships the
        key commented out, and treating that as "already configured" would
        install a backend that cannot start.
    #>
    param([string]$ConfigFile)

    if (-not (Test-Path -LiteralPath $ConfigFile)) { return $null }

    try {
        $lines = Get-Content -LiteralPath $ConfigFile -ErrorAction Stop
    } catch {
        # The file is deliberately readable only by Administrators and SYSTEM.
        # Guessing that there is no secret here would generate a new one and
        # sign out every user, so this stops instead.
        throw ("Cannot read $ConfigFile, which holds the session secret. " +
               "Re-run from an elevated prompt: continuing would generate a new " +
               "secret and sign out every user.")
    }

    foreach ($line in $lines) {
        if ($line -match '^\s*SYSWATCH_SESSION_SECRET\s*=\s*(\S.*)$') {
            return $matches[1].Trim()
        }
    }

    return $null
}

function Copy-Tree {
    param([string]$Source, [string]$Destination, [string[]]$Exclude = @())

    if (-not (Test-Path -LiteralPath $Destination)) {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }

    $arguments = @($Source, $Destination, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:2', '/W:1')
    foreach ($item in $Exclude) {
        $arguments += @('/XD', $item)
    }

    robocopy @arguments | Out-Null

    # robocopy exits 0-7 for success (bit 3 and above are failures). Anything
    # else here would otherwise read as a failed command to $LASTEXITCODE.
    if ($LASTEXITCODE -ge 8) {
        throw "Copying $Source to $Destination failed (robocopy exit $LASTEXITCODE)."
    }

    $global:LASTEXITCODE = 0
}

function Invoke-Native {
    <#
        Run a native command and judge it by its exit code alone.

        Windows PowerShell turns anything a native command writes to stderr
        into a terminating error while $ErrorActionPreference is Stop. pip
        warns to stderr as a matter of course, and `python -m venv` reports a
        redirected path the same way, so an install would abort on a message
        that was not even a failure. Only the exit code decides here; the
        output is kept and shown when it turns out to matter.
    #>
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$What,
        [switch]$ShowOutput,
        [switch]$Capture
    )

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($WorkingDirectory) { Push-Location $WorkingDirectory }
        try {
            $output = & $Executable @Arguments 2>&1
            $code = $LASTEXITCODE
        } finally {
            if ($WorkingDirectory) { Pop-Location }
        }
    } finally {
        $ErrorActionPreference = $previous
    }

    if ($code -ne 0) {
        foreach ($line in $output) { Write-Host "    $line" -ForegroundColor Red }
        throw "$What failed (exit $code)."
    }

    if ($ShowOutput.IsPresent) {
        foreach ($line in $output) { Write-Detail $line }
    }

    if ($Capture.IsPresent) {
        return $output
    }
}

function Invoke-Interactive {
    <#
        For a command that must keep the console: create_admin reads a password
        from a hidden prompt, and capturing its output would leave the operator
        typing into nothing.
    #>
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$What
    )

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        Push-Location $WorkingDirectory
        try {
            & $Executable @Arguments
            $code = $LASTEXITCODE
        } finally {
            Pop-Location
        }
    } finally {
        $ErrorActionPreference = $previous
    }

    if ($code -ne 0) {
        throw "$What failed (exit $code)."
    }
}

# --- prerequisites -----------------------------------------------------------

Write-Step "Checking prerequisites"

$problems = @()

if (-not $SkipServices.IsPresent -and -not (Test-Administrator)) {
    $problems += "Not running as administrator. Registering a service needs it; re-run from an elevated prompt, or pass -SkipServices to install the files only."
}

$agentBinary = Join-Path $SourceRoot 'agent\build\agent.exe'
if (-not (Test-Path -LiteralPath $agentBinary)) {
    $problems += "No agent at $agentBinary. Build it first: cmake -S agent -B agent/build -G Ninja; cmake --build agent/build"
}

$dashboardDist = Join-Path $SourceRoot 'dashboard\dist'
if (-not (Test-Path -LiteralPath (Join-Path $dashboardDist 'index.html'))) {
    $problems += "No built dashboard at $dashboardDist. Build it first: cd dashboard; npm ci; npm run build"
}

$backendSource = Join-Path $SourceRoot 'backend'
if (-not (Test-Path -LiteralPath (Join-Path $backendSource 'serve.py'))) {
    $problems += "No backend at $backendSource."
}

$python = Get-PythonCommand
if (-not $python) {
    $problems += "No Python $MinimumPython or newer on PATH."
}

if ($problems.Count -gt 0) {
    Write-Host ""
    Write-Host "Cannot install:" -ForegroundColor Red
    foreach ($problem in $problems) { Write-Host "  * $problem" -ForegroundColor Red }
    exit 1
}

Write-Detail "Python $($python.Version) ($($python.Command))"
Write-Detail "Source: $SourceRoot"

$versionFile = Join-Path $SourceRoot 'VERSION'
$version = if (Test-Path -LiteralPath $versionFile) {
    (Get-Content -LiteralPath $versionFile -Raw).Trim()
} else {
    'unknown'
}
Write-Detail "Version: $version"

$isUpgrade = Test-Path -LiteralPath (Join-Path $InstallRoot 'backend\serve.py')
if ($isUpgrade) {
    Write-Detail "Existing install found at $InstallRoot - this is an upgrade."
}

# Set before anything runs out of the install, not just before alembic. The
# backup below reads the database location from configuration, and without this
# it resolves the default %PROGRAMDATA%\SysWatch instead of this install's data
# directory - backing up a different database, or an empty new one, and
# reporting success either way. A backup of the wrong file is worse than none.
$configFile = Join-Path $DataDir $ConfigFileName
$env:SYSWATCH_CONFIG_FILE = $configFile

# --- back up before changing anything ----------------------------------------

$databaseFile = Join-Path $DataDir 'syswatch.db'

if ($isUpgrade -and (Test-Path -LiteralPath $databaseFile)) {
    Write-Step "Backing up the database"

    $existingPython = Join-Path $InstallRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $existingPython) {
        $backupDir = Join-Path $DataDir 'backups'
        try {
            Invoke-Native -Executable $existingPython `
                -Arguments @('-m', 'app.db.backup', $backupDir, '--keep', '10') `
                -WorkingDirectory (Join-Path $InstallRoot 'backend') `
                -What 'Backup' -ShowOutput
        } catch {
            # An upgrade that cannot back up is one to stop, not to push
            # through: the migration is the step most likely to need the backup.
            Write-Host ""
            Write-Host "Backup failed, so the upgrade has stopped before touching the database." -ForegroundColor Red
            Write-Host $_.Exception.Message -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Warn "No interpreter in the existing install; skipping the pre-upgrade backup."
    }
}

# --- stop services before replacing the files they are running ---------------

if (-not $SkipServices.IsPresent -and $isUpgrade) {
    Write-Step "Stopping services"
    foreach ($name in @($BackendServiceName, $AgentServiceName)) {
        $service = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($service -and $service.Status -ne 'Stopped') {
            Stop-Service -Name $name -Force
            Write-Detail "Stopped $name"
        }
    }
}

# --- files -------------------------------------------------------------------

Write-Step "Installing to $InstallRoot"

New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $InstallRoot 'agent') -Force | Out-Null

Copy-Item -LiteralPath $agentBinary -Destination (Join-Path $InstallRoot 'agent\agent.exe') -Force
Write-Detail "agent.exe"

# .venv is excluded: it holds absolute paths from wherever it was built, and is
# rebuilt below in the install directory. __pycache__ and tests are not part of
# a deployment.
Copy-Tree -Source $backendSource -Destination (Join-Path $InstallRoot 'backend') `
    -Exclude @('.venv', '__pycache__', 'tests', '.pytest_cache', 'data')
Write-Detail "backend"

Copy-Tree -Source $dashboardDist -Destination (Join-Path $InstallRoot 'dashboard')
Write-Detail "dashboard"

if (Test-Path -LiteralPath $versionFile) {
    Copy-Item -LiteralPath $versionFile -Destination (Join-Path $InstallRoot 'backend\VERSION') -Force
}

# --- data directory and configuration ----------------------------------------

Write-Step "Preparing $DataDir"

New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $DataDir 'logs') -Force | Out-Null

$existingSecret = Get-ExistingSessionSecret -ConfigFile $configFile

if ($existingSecret) {
    Write-Detail "Keeping the existing session secret."
    $secret = $existingSecret
} else {
    Write-Detail "Generating a session secret."
    $secret = New-SessionSecret
}

$dashboardInstalled = Join-Path $InstallRoot 'dashboard'
$configLines = @(
    "# SysWatch configuration, written by Install-SysWatch.ps1."
    "# Environment variables override anything set here."
    "#"
    "# SYSWATCH_SESSION_SECRET is the HMAC key for every session token."
    "# Changing it signs every user out. The installer never regenerates it."
    ""
    "SYSWATCH_SESSION_SECRET=$secret"
    "SYSWATCH_DATA_DIR=$DataDir"
    "SYSWATCH_DASHBOARD_DIR=$dashboardInstalled"
    "SYSWATCH_HOST=127.0.0.1"
    "SYSWATCH_PORT=$Port"
    "SYSWATCH_AGENT_BASE_URL=http://127.0.0.1:8080"
)

Set-Content -LiteralPath $configFile -Value $configLines -Encoding utf8
Write-Detail "Wrote $configFile"

# The config file has the session secret in it, so inheritance is broken and
# the list is rebuilt: SYSTEM because the services run as LocalSystem, and
# Administrators because that is who maintains the install.
#
# The installing user is added when this is not an elevated run, which only
# happens under -SkipServices. Without that, the script would lock itself out
# of the file it is about to read - and so would the operator staging the
# install, for a secret they just generated.
$grants = @('*S-1-5-32-544:(F)', '*S-1-5-18:(F)')
if (-not (Test-Administrator)) {
    $grants += ('{0}:(F)' -f [Security.Principal.WindowsIdentity]::GetCurrent().Name)
}

try {
    icacls $configFile /inheritance:r /grant:r @grants | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls exited $LASTEXITCODE" }
    Write-Detail "Restricted $ConfigFileName to Administrators and SYSTEM."
} catch {
    Write-Warn "Could not restrict permissions on $configFile. It contains the session secret; check who can read it."
}

# --- python environment ------------------------------------------------------

Write-Step "Installing Python dependencies"

$venv = Join-Path $InstallRoot '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    Invoke-Native -Executable $python.Command -Arguments @('-m', 'venv', $venv) `
        -What "Creating a virtual environment at $venv"
    Write-Detail "Created $venv"
}

Invoke-Native -Executable $venvPython `
    -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip', '--quiet') `
    -What 'Upgrading pip'
Invoke-Native -Executable $venvPython `
    -Arguments @('-m', 'pip', 'install', '-r', (Join-Path $InstallRoot 'backend\requirements.txt'), '--quiet') `
    -What 'Installing dependencies'
Write-Detail "Dependencies installed."

# --- schema ------------------------------------------------------------------

Write-Step "Migrating the database"

Invoke-Native -Executable $venvPython -Arguments @('-m', 'alembic', 'upgrade', 'head') `
    -WorkingDirectory (Join-Path $InstallRoot 'backend') -What 'alembic upgrade head'
Write-Detail "Schema is current."

# --- first account -----------------------------------------------------------

if (-not $SkipAdminAccount.IsPresent) {
    # From the install's backend directory, like every other call into it. Run
    # from wherever the operator happened to be, "app" is not importable and
    # this raised a traceback instead of returning a number.
    $countAccounts = 'from app.db import init_engine; from app.repositories import UserStore; init_engine(); print(UserStore().count())'

    $accountCount = $null
    try {
        $accountCount = Invoke-Native -Executable $venvPython -Arguments @('-c', $countAccounts) `
            -WorkingDirectory (Join-Path $InstallRoot 'backend') `
            -What 'Counting accounts' -Capture
    } catch {
        # Not fatal. The install is complete either way, and an operator who is
        # told to run one command is better off than one whose install stopped
        # after copying the files.
        Write-Warn "Could not count existing accounts: $($_.Exception.Message)"
    }

    if ($null -eq $accountCount) {
        Write-Warn "Create the first account with:"
        Write-Warn "  cd `"$InstallRoot\backend`"; .\..\.venv\Scripts\python.exe -m app.auth.create_admin"
    } elseif ("$accountCount".Trim() -eq '0') {
        Write-Step "Creating the first account"
        Write-Detail "The password is read from a hidden prompt and is not echoed."
        try {
            Invoke-Interactive -Executable $venvPython -Arguments @('-m', 'app.auth.create_admin') `
                -WorkingDirectory (Join-Path $InstallRoot 'backend') -What 'Creating the first account'
        } catch {
            # Two mistyped passwords should not undo an install. Everything
            # that matters is already in place; the services still need
            # registering, and this is a command that can be repeated.
            Write-Warn "No account was created."
            Write-Warn "Run this when ready, then log in:"
            Write-Warn "  cd `"$InstallRoot\backend`"; `"$venvPython`" -m app.auth.create_admin"
        }
    } else {
        Write-Detail "$accountCount account(s) already exist; not prompting."
    }
}

# --- services ----------------------------------------------------------------

if ($SkipServices.IsPresent) {
    Write-Step "Skipping service registration (-SkipServices)"
    Write-Detail "To finish by hand, from an elevated prompt:"
    Write-Detail "  setx /M SYSWATCH_CONFIG_FILE `"$configFile`""
    Write-Detail "  `"$InstallRoot\agent\agent.exe`" --install"
    Write-Detail "  nssm install $BackendServiceName `"$venvPython`" `"$InstallRoot\backend\serve.py`""
    Write-Detail "  nssm set $BackendServiceName AppDirectory `"$InstallRoot\backend`""
} else {
    Write-Step "Registering services"

    [Environment]::SetEnvironmentVariable('SYSWATCH_CONFIG_FILE', $configFile, 'Machine')
    Write-Detail "Set SYSWATCH_CONFIG_FILE for the machine."

    $agentBinaryInstalled = Join-Path $InstallRoot 'agent\agent.exe'
    $expectedPath = '"{0}" --service' -f $agentBinaryInstalled
    $registeredPath = $null

    if (Get-Service -Name $AgentServiceName -ErrorAction SilentlyContinue) {
        $registeredPath = (Get-CimInstance Win32_Service -Filter "Name='$AgentServiceName'").PathName
    }

    if ($registeredPath -eq $expectedPath) {
        # The normal case on an upgrade. Asking agent.exe to install over
        # itself only produces "already installed. Run --uninstall first" and
        # a non-zero exit, which reads as a broken upgrade when nothing is
        # wrong at all.
        Write-Detail "$AgentServiceName already registered."
    } else {
        if ($registeredPath) {
            # An install into a different directory leaves the registration
            # pointing at the old binary, so the service keeps running the
            # version that was just replaced - an upgrade that reports success
            # and changes nothing.
            Write-Detail "Re-registering $AgentServiceName, which points at $registeredPath"
            try {
                Invoke-Native -Executable $agentBinaryInstalled -Arguments @('--uninstall') `
                    -What 'Removing the previous registration'
            } catch {
                Write-Warn $_.Exception.Message
            }
        }

        try {
            Invoke-Native -Executable $agentBinaryInstalled -Arguments @('--install') `
                -What 'Registering the agent service'
            Write-Detail "$AgentServiceName registered."
        } catch {
            Write-Warn $_.Exception.Message
        }
    }

    # The backend is a Python process and does not speak the service control
    # protocol. `sc.exe create` would register it and the SCM would kill it for
    # not reporting SERVICE_RUNNING, which looks like a broken install rather
    # than a missing dependency - so it is not attempted without a host that
    # can do the job.
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
    if ($nssm) {
        $existing = Get-Service -Name $BackendServiceName -ErrorAction SilentlyContinue
        if (-not $existing) {
            & $nssm.Source install $BackendServiceName $venvPython (Join-Path $InstallRoot 'backend\serve.py')
            & $nssm.Source set $BackendServiceName AppDirectory (Join-Path $InstallRoot 'backend')
            & $nssm.Source set $BackendServiceName Start SERVICE_AUTO_START
            & $nssm.Source set $BackendServiceName AppStdout (Join-Path $DataDir 'logs\backend-stdout.log')
            & $nssm.Source set $BackendServiceName AppStderr (Join-Path $DataDir 'logs\backend-stderr.log')
            Write-Detail "$BackendServiceName registered via nssm."
        } else {
            Write-Detail "$BackendServiceName already registered."
        }
    } else {
        Write-Warn "nssm is not installed, so the backend was not registered as a service."
        Write-Warn "Install it (choco install nssm) and re-run, or start the backend with:"
        Write-Warn "  $venvPython $InstallRoot\backend\serve.py"
    }

    Write-Step "Starting services"
    foreach ($name in @($AgentServiceName, $BackendServiceName)) {
        $service = Get-Service -Name $name -ErrorAction SilentlyContinue
        if (-not $service) { continue }

        try {
            Start-Service -Name $name
            Write-Detail "$name started."
        } catch {
            Write-Warn "$name did not start: $($_.Exception.Message)"
            Write-Warn "Check $DataDir\logs."
        }
    }
}

# --- done --------------------------------------------------------------------

Write-Host ""
Write-Host "SysWatch $version is installed." -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard:  http://127.0.0.1:$Port/"
Write-Host "  Config:     $configFile"
Write-Host "  Data:       $DataDir"
Write-Host "  Logs:       $(Join-Path $DataDir 'logs')"
Write-Host ""

# Explicit, because $LASTEXITCODE still holds whatever the last native command
# returned. A step that was allowed to fail without stopping the install - a
# mistyped password, a service that would not start - would otherwise leave a
# finished install reporting failure to whoever checked.
exit 0
