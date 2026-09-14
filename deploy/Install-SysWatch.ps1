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

.PARAMETER InstallPrerequisites
    Install a missing prerequisite without asking. Without it, an interactive
    run offers to install and defaults to no, and an unattended run refuses
    and says what is missing.

.PARAMETER BackendUrl
    The ingest endpoint this machine's agent pushes its snapshots to, on a
    backend somewhere else. The full URL, like
    http://backend:8000/api/ingest/snapshot

.PARAMETER AgentToken
    The credential the agent presents when pushing. Issue one on the backend:
        python -m app.auth.create_agent_token --host <name>

    -BackendUrl and -AgentToken go together, and the pair replaces whatever
    this machine was pushing before. Leaving both out is not "turn pushing
    off": an upgrade with neither keeps the settings already in the config
    file, and a first install with neither is the single-machine install this
    script has always done, where the agent serves 127.0.0.1 and the backend
    beside it polls.

.PARAMETER AllowInsecurePush
    Permit an http:// backend that is not this machine. The agent speaks no
    TLS yet, so the token would cross the network readable by anything on the
    path. See docs/decisions/0002-the-agent-speaks-tls-through-winhttp.md

.EXAMPLE
    .\Install-SysWatch.ps1

.EXAMPLE
    .\Install-SysWatch.ps1 -InstallRoot D:\SysWatch -Port 9000

.EXAMPLE
    Report to a backend on another machine, over a trusted network:

    .\Install-SysWatch.ps1 -BackendUrl http://backend:8000/api/ingest/snapshot `
        -AgentToken $token -AllowInsecurePush
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = "$env:ProgramFiles\SysWatch",
    [string]$DataDir = "$env:ProgramData\SysWatch",
    [int]$Port = 8000,
    [string]$SourceRoot,
    [switch]$SkipServices,
    [switch]$SkipAdminAccount,
    [switch]$InstallPrerequisites,
    [string]$BackendUrl,
    [string]$AgentToken,
    [switch]$AllowInsecurePush
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

function Update-PathFromRegistry {
    <#
        Adopt a PATH that changed after this process started.

        winget writes the new entry to the registry, and a running process
        keeps the environment block it was given at launch - so without this,
        the installer would install Python and then still not find it.
    #>
    $machine = [Environment]::GetEnvironmentVariable('PATH', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('PATH', 'User')
    $env:PATH = @($machine, $user) -ne $null -join ';'
}

function Approve-PrerequisiteInstall {
    <#
        Whether to install a missing prerequisite.

        Asked, not assumed. Installing a system-wide language runtime changes
        machine PATH and can collide with an interpreter already in use, so it
        defaults to no and is skipped entirely when nobody is at the keyboard -
        a prompt in a deployment pipeline is a hang, not a question.
    #>
    param([string]$What)

    if ($InstallPrerequisites.IsPresent) { return $true }
    if (-not [Environment]::UserInteractive) { return $false }
    if ([Console]::IsInputRedirected) { return $false }

    Write-Host ""
    Write-Host "    $What is missing." -ForegroundColor Yellow
    Write-Host "    It can be installed now with winget, for the whole machine."
    Write-Host "    A per-user install would not be visible to the services, which run as LocalSystem."
    $answer = Read-Host "    Install it? [y/N]"

    return $answer -match '^\s*(y|yes)\s*$'
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

function Get-ExistingSetting {
    <#
        One setting already in the config file, or $null.

        This script rewrites the whole file on every run, so anything it does
        not deliberately carry forward is dropped on upgrade. That is silent
        by construction, which is why the settings it matters for are read
        back through here rather than assumed.

        Only an uncommented assignment counts. syswatch.env.example ships every
        key commented out, and treating that as "already configured" would
        install a backend that cannot start.
    #>
    param(
        [string]$ConfigFile,
        [string]$Name,
        # What being wrong about this would cost, for the message below.
        [string]$Consequence
    )

    if (-not (Test-Path -LiteralPath $ConfigFile)) { return $null }

    try {
        $lines = Get-Content -LiteralPath $ConfigFile -ErrorAction Stop
    } catch {
        # The file is deliberately readable only by Administrators and SYSTEM.
        # Treating unreadable as absent would drop the setting on the write
        # below, so this stops instead.
        throw ("Cannot read $ConfigFile, which holds $Name. " +
               "Re-run from an elevated prompt: $Consequence")
    }

    $assignment = '^\s*' + [regex]::Escape($Name) + '\s*=\s*(\S.*)$'
    foreach ($line in $lines) {
        if ($line -match $assignment) {
            return $matches[1].Trim()
        }
    }

    return $null
}

function Test-LoopbackHost {
    <#
        Whether a host name means "this machine", by the same rule the agent
        uses - 127.0.0.0/8 in full, not just 127.0.0.1, because calling
        127.0.0.2 remote would refuse a working local configuration.

        [uri] renders an IPv6 literal with its brackets, so both spellings of
        ::1 are matched here.
    #>
    param([string]$HostName)

    if ($HostName -eq 'localhost' -or $HostName -eq '::1' -or $HostName -eq '[::1]') {
        return $true
    }

    if ($HostName -match '^(\d{1,3})\.\d{1,3}\.\d{1,3}\.\d{1,3}$') {
        return ([int]$matches[1] -eq 127)
    }

    return $false
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

# -BackendUrl and -AgentToken are checked here, with everything else that
# would stop an install, so a mistyped address is reported before any file is
# copied. The rules are the agent's own startup rules, applied early: being
# told now is better than finding a service that will not start.
$configuresPush = $BackendUrl -or $AgentToken -or $AllowInsecurePush.IsPresent

if ($configuresPush) {
    if (-not $BackendUrl -or -not $AgentToken) {
        # Half a configuration is refused rather than half applied. A URL with
        # no token is 401 on every push; a token with no URL has nowhere to go.
        $problems += (
            "Pushing to a backend needs both -BackendUrl and -AgentToken. " +
            "Together they replace whatever this machine was pushing before; " +
            "leave both out to keep what is already configured. Issue a token " +
            "on the backend with: python -m app.auth.create_agent_token --host <name>"
        )
    } else {
        $destination = $null
        if (-not [uri]::TryCreate($BackendUrl, [UriKind]::Absolute, [ref]$destination) -or
            ($destination.Scheme -ne 'http' -and $destination.Scheme -ne 'https')) {
            $problems += (
                "-BackendUrl is not an http address: $BackendUrl. It is the full " +
                "ingest endpoint, like http://backend:8000/api/ingest/snapshot"
            )
        } elseif ($destination.Scheme -eq 'https') {
            $problems += (
                "-BackendUrl is https, which this agent cannot speak yet. Terminate " +
                "TLS in front of the backend and give the agent the http:// address " +
                "behind it. See docs/decisions/0002-the-agent-speaks-tls-through-winhttp.md"
            )
        } elseif (-not (Test-LoopbackHost $destination.Host) -and -not $AllowInsecurePush.IsPresent) {
            # The one that matters. A token sent in clear to another machine is
            # readable by anything on the path, and a stolen agent token writes
            # any history it likes for the host it names.
            $problems += (
                "-BackendUrl points off this machine over plain HTTP, so the agent's " +
                "token would cross the network in clear on every push. Put TLS in " +
                "front of the backend, or pass -AllowInsecurePush if the network " +
                "between these machines is genuinely trusted."
            )
        }
    }
}

$python = Get-PythonCommand

if (-not $python -and (Test-Administrator)) {
    # Offered here rather than left to a second script the operator has to know
    # about. Install-Prerequisites.ps1 is still what does the work - this asks,
    # and calls it.
    $prerequisites = Join-Path $PSScriptRoot 'Install-Prerequisites.ps1'

    if ((Test-Path -LiteralPath $prerequisites) -and (Approve-PrerequisiteInstall "Python $MinimumPython or newer")) {
        try {
            & $prerequisites -Install
            Update-PathFromRegistry
            $python = Get-PythonCommand

            if ($python) {
                Write-Detail "Python $($python.Version) is now available."
            } else {
                # winget can report success while the interpreter lands
                # somewhere this process still cannot see.
                Write-Warn "Python was installed but is not on PATH yet. Open a new prompt and re-run this."
            }
        } catch {
            Write-Warn "Could not install Python: $($_.Exception.Message)"
        }
    }
}

if (-not $python) {
    # The one prerequisite a clean machine will not have, and the message an
    # operator meets first. "Not found" on its own leaves them to guess whether
    # the problem is the version, the PATH, or the Store alias.
    $problems += (
        "No Python $MinimumPython or newer on PATH. Re-run this from an " +
        "elevated prompt and it will offer to install one, or pass " +
        "-InstallPrerequisites to skip the question. To see everything this " +
        "machine is missing first: .\Install-Prerequisites.ps1. If 'python' " +
        "opens the Microsoft Store instead of running, turn off the App " +
        "Execution Alias for it in Settings."
    )
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

$existingSecret = Get-ExistingSetting -ConfigFile $configFile `
    -Name 'SYSWATCH_SESSION_SECRET' `
    -Consequence 'continuing would generate a new secret and sign out every user.'

if ($existingSecret) {
    Write-Detail "Keeping the existing session secret."
    $secret = $existingSecret
} else {
    Write-Detail "Generating a session secret."
    $secret = New-SessionSecret
}

# What this machine pushes, and where. Parameters replace it; no parameters
# keeps whatever the file already says.
#
# Carried forward explicitly, because the failure of forgetting is a quiet one:
# the machine would install cleanly, run, serve loopback, and simply stop
# reporting. The only symptom is a host going stale on a dashboard somebody
# else is looking at, with nothing in any log here to explain it.
$agentLines = @()

if ($configuresPush) {
    $agentLines += "SYSWATCH_AGENT_BACKEND_URL=$BackendUrl"
    $agentLines += "SYSWATCH_AGENT_TOKEN=$AgentToken"
    if ($AllowInsecurePush.IsPresent) {
        $agentLines += "SYSWATCH_AGENT_ALLOW_INSECURE_PUSH=true"
    }
    # The URL, never the token. This console output is what an operator pastes
    # into a ticket when an install goes wrong.
    Write-Detail "Pushing snapshots to $BackendUrl"
} else {
    foreach ($name in @('SYSWATCH_AGENT_BACKEND_URL',
                        'SYSWATCH_AGENT_TOKEN',
                        'SYSWATCH_AGENT_ALLOW_INSECURE_PUSH')) {
        $kept = Get-ExistingSetting -ConfigFile $configFile -Name $name `
            -Consequence 'continuing would drop this machine''s push configuration and it would stop reporting.'
        if ($kept) { $agentLines += "$name=$kept" }
    }

    if ($agentLines.Count -gt 0) {
        Write-Detail "Keeping the existing push configuration."
    }
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

if ($agentLines.Count -gt 0) {
    $configLines += @(
        ""
        "# Read by the agent rather than the backend: where this machine pushes"
        "# its snapshots, and the credential it presents. The token is one of the"
        "# two reasons this file is readable only by Administrators and SYSTEM."
    )
    $configLines += $agentLines
}

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
    Write-Warn "Could not restrict permissions on $configFile. It contains the session secret and any agent token; check who can read it."
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
    Write-Detail "  setx /M SYSWATCH_AGENT_CONFIG_FILE `"$configFile`""
    Write-Detail "  `"$InstallRoot\agent\agent.exe`" --install"
    Write-Detail "  nssm install $BackendServiceName `"$venvPython`" `"$InstallRoot\backend\serve.py`""
    Write-Detail "  nssm set $BackendServiceName AppDirectory `"$InstallRoot\backend`""
} else {
    Write-Step "Registering services"

    [Environment]::SetEnvironmentVariable('SYSWATCH_CONFIG_FILE', $configFile, 'Machine')
    Write-Detail "Set SYSWATCH_CONFIG_FILE for the machine."

    # The agent reads the same file, and looks for it in %PROGRAMDATA%\SysWatch
    # unless told otherwise - which is the wrong place whenever -DataDir points
    # somewhere else. Without this, such an install writes a push configuration
    # the agent never reads.
    #
    # This is the only agent setting that may come from the environment, and
    # only because it is a path rather than a value: a machine-wide variable on
    # Windows is readable by every account on it, which is no place for a token.
    [Environment]::SetEnvironmentVariable('SYSWATCH_AGENT_CONFIG_FILE', $configFile, 'Machine')
    Write-Detail "Set SYSWATCH_AGENT_CONFIG_FILE for the machine."

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
        $serveScript = Join-Path $InstallRoot 'backend\serve.py'
        $backendDirectory = Join-Path $InstallRoot 'backend'

        # Every one of these goes through Invoke-Native. nssm reports what it
        # did on stderr, and a bare call would abort the install on a message
        # that was not a failure.
        $settings = @(
            @('set', $BackendServiceName, 'AppDirectory', $backendDirectory),
            # serve.py, relative, not the full path.
            #
            # nssm stores AppParameters as one string and the launcher splits
            # it on spaces, so an absolute path under "C:\Program Files" is
            # handed to Python as `C:\Program` - which is every default
            # install. Quoting it would work, but getting literal quotes
            # through PowerShell into a native command is its own fight.
            # AppDirectory is already the backend directory, so a bare
            # filename has no space in it and needs no quoting at all.
            @('set', $BackendServiceName, 'AppParameters', 'serve.py'),
            @('set', $BackendServiceName, 'Start', 'SERVICE_AUTO_START'),
            @('set', $BackendServiceName, 'AppStdout', (Join-Path $DataDir 'logs\backend-stdout.log')),
            @('set', $BackendServiceName, 'AppStderr', (Join-Path $DataDir 'logs\backend-stderr.log')),
            # The backend is what the dashboard is served from; if it exits,
            # bring it back rather than leaving a monitoring system dark.
            @('set', $BackendServiceName, 'AppExit', 'Default', 'Restart')
        )

        $existing = Get-Service -Name $BackendServiceName -ErrorAction SilentlyContinue
        $registeredApp = $null
        if ($existing) {
            try {
                $registeredApp = (Invoke-Native -Executable $nssm.Source `
                    -Arguments @('get', $BackendServiceName, 'Application') `
                    -What 'Reading the backend service' -Capture) -join ''
            } catch {
                Write-Warn $_.Exception.Message
            }
        }

        try {
            if ($existing -and $registeredApp -and $registeredApp.Trim() -ne $venvPython) {
                # Same trap as the agent: an install into a different directory
                # leaves the registration running the interpreter that was just
                # replaced, and the upgrade silently changes nothing.
                Write-Detail "Re-pointing $BackendServiceName, which runs $($registeredApp.Trim())"
                Invoke-Native -Executable $nssm.Source `
                    -Arguments @('set', $BackendServiceName, 'Application', $venvPython) `
                    -What 'Re-pointing the backend service'
            } elseif (-not $existing) {
                Invoke-Native -Executable $nssm.Source `
                    -Arguments @('install', $BackendServiceName, $venvPython) `
                    -What 'Registering the backend service'
            }

            foreach ($arguments in $settings) {
                Invoke-Native -Executable $nssm.Source -Arguments $arguments `
                    -What "nssm $($arguments -join ' ')"
            }

            # nssm can report success and still leave nothing registered if the
            # SCM refused it, so this asks the SCM rather than trusting nssm.
            if (Get-Service -Name $BackendServiceName -ErrorAction SilentlyContinue) {
                Write-Detail "$BackendServiceName registered via nssm."
            } else {
                Write-Warn "nssm reported success but $BackendServiceName is not registered."
            }
        } catch {
            Write-Warn $_.Exception.Message
            Write-Warn "Start the backend by hand with:"
            Write-Warn "  `"$venvPython`" `"$serveScript`""
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
if ($agentLines.Count -gt 0 -and $BackendUrl) {
    Write-Host "  Pushing to: $BackendUrl"
} elseif ($agentLines.Count -gt 0) {
    Write-Host "  Pushing to: (kept from the existing configuration)"
}
Write-Host "  Config:     $configFile"
Write-Host "  Data:       $DataDir"
Write-Host "  Logs:       $(Join-Path $DataDir 'logs')"
Write-Host ""

# Explicit, because $LASTEXITCODE still holds whatever the last native command
# returned. A step that was allowed to fail without stopping the install - a
# mistyped password, a service that would not start - would otherwise leave a
# finished install reporting failure to whoever checked.
exit 0
