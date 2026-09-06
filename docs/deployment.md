# Deploying SysWatch

Installing, upgrading, operating and removing SysWatch on a Windows machine.

Everything here has been run against a real install. Where a step has a trap in
it, the trap is written down rather than left to be discovered.

## What gets installed

```text
C:\Program Files\SysWatch\          the program. Replaced wholesale on upgrade.
    agent\agent.exe                 the collector, registered as SysWatchAgent
    backend\                        FastAPI application and migrations
    dashboard\                      the built site the backend serves
    .venv\                          Python environment, built during install

C:\ProgramData\SysWatch\            the data. Never touched by an upgrade.
    syswatch.db                     snapshots, alerts, accounts, sessions
    syswatch.env                    configuration, including the session secret
    logs\                           agent.log and syswatch.log, both rotating
    backups\                        written by the installer and on demand
```

The split is the point: uninstalling removes the first tree and leaves the
second. Monitoring history outlives the software that collected it.

## Requirements

- Windows 10 or 11, or Windows Server 2019 or newer
- Python 3.10 or newer on `PATH` (tested on 3.10 and 3.14 in CI)
- An administrator prompt, for registering services
- `nssm`, optionally - see [The backend as a service](#the-backend-as-a-service)

**The installer offers to install Python if it is missing**, from an elevated
prompt, and defaults to no. Answer yes and it installs it machine-wide with
winget, re-reads PATH and carries on in the same run - a per-user install would
satisfy the check and then not exist for the services, which run as LocalSystem.

`-InstallPrerequisites` answers yes in advance, for unattended installs. When
nobody is at the keyboard the question is skipped entirely rather than asked
into a pipeline that cannot answer it, and the install refuses with a message
saying what is missing.

To see what the machine needs without running the installer at all:

```text
powershell -ExecutionPolicy Bypass -File deploy\Install-Prerequisites.ps1
```

That reports and changes nothing. `-Install` installs what it found, and
`-IncludeBuildTools` also covers the compiler, CMake, Ninja and Node needed to
build from source.

Build the agent and the dashboard first, or use a release archive, which
contains both already built:

```text
cmake -S agent -B agent\build -G Ninja
cmake --build agent\build
cd dashboard && npm ci && npm run build
```

## Installing

From an **elevated** prompt:

```text
powershell -ExecutionPolicy Bypass -File deploy\Install-SysWatch.ps1
```

It checks prerequisites, copies the three components into
`C:\Program Files\SysWatch`, prepares `C:\ProgramData\SysWatch`, generates a
session secret, builds a virtual environment, migrates the database, prompts
for the first account, and registers and starts the services.

The password prompt asks twice and echoes nothing. The policy is **at least 12
characters, mixing at least two of** lower case, upper case, digits, symbols.
Nothing else - composition rules beyond that push people towards `Password1!`.

Useful parameters:

| Parameter | Default | For |
| --- | --- | --- |
| `-InstallRoot` | `C:\Program Files\SysWatch` | Installing elsewhere |
| `-DataDir` | `C:\ProgramData\SysWatch` | Putting data on another volume |
| `-Port` | `8000` | When 8000 is taken |
| `-SkipServices` | off | Staging an install without touching the SCM. Needs no administrator rights. |
| `-SkipAdminAccount` | off | Unattended installs; create the account afterwards |

### After installing: open a new terminal

The installer sets `SYSWATCH_CONFIG_FILE` as a **machine** environment
variable. Windows hands that to processes started afterwards, so services get
it, but the terminal you ran the installer from does not - it inherited its
environment before the variable existed.

If you want to run backend commands from that same window, set it yourself:

```text
set SYSWATCH_CONFIG_FILE=C:\ProgramData\SysWatch\syswatch.env
```

Without it, commands still find the database, because the default data
directory is the same `%PROGRAMDATA%\SysWatch`. But `syswatch.env` is where the
session secret lives, and the backend refuses to start without one - so
`serve.py` fails and `create_admin` succeeds, which is a confusing pair of
outcomes to debug.

### Everything backend needs elevation

`syswatch.env` holds the session secret, so the installer restricts it to
Administrators and SYSTEM. Any command that reads configuration - `serve.py`,
`create_admin`, `app.db.backup` - must therefore run elevated. A normal prompt
gets a permission error on the config file, not a helpful message.

## The backend as a service

The agent is a real Windows service: one binary, dispatching to
`StartServiceCtrlDispatcher` when started with `--service`.

The backend is a Python process and does not speak the service control
protocol. `sc.exe create` would register it and the SCM would then kill it for
never reporting `SERVICE_RUNNING` - which looks like a broken install rather
than a missing dependency. So the installer does not attempt it. Instead:

```text
choco install nssm -y
```

Re-run the installer and it registers `SysWatchBackend` through nssm, with
`AppDirectory` set and stdout and stderr going to `logs\`.

Without nssm the install is complete and correct; the backend is simply started
by hand, and the installer prints the command:

```text
"C:\Program Files\SysWatch\.venv\Scripts\python.exe" "C:\Program Files\SysWatch\backend\serve.py"
```

## Upgrading

The same command. The installer detects an existing install and takes the
upgrade path:

```text
powershell -ExecutionPolicy Bypass -File deploy\Install-SysWatch.ps1
```

Four things it does differently, all of which matter:

1. **Backs up the database first**, with `VACUUM INTO`, and verifies the result
   before continuing. If the backup fails the upgrade stops there, because the
   migration is the step most likely to need it.
2. **Keeps the existing session secret.** It is the HMAC key for every session
   token; regenerating it would sign every user out on every deploy. The log
   line reads `Keeping the existing session secret` - if it ever says
   `Generating`, stop and find out why.
3. **Stops the services** before replacing the files they are running from.
4. **Does not prompt for an account** when one already exists.

The data directory is not touched beyond the migration and the backup.

## Uninstalling

```text
powershell -ExecutionPolicy Bypass -File deploy\Uninstall-SysWatch.ps1
```

Stops and deregisters the services, removes `C:\Program Files\SysWatch`, and
clears the machine environment variable. **The data directory is kept.**

To remove the data as well:

```text
powershell -ExecutionPolicy Bypass -File deploy\Uninstall-SysWatch.ps1 -RemoveData
```

That prompts for the word `DELETE` before deleting the database, the accounts
and the logs. `-Force` skips the prompt, for scripted teardown.

## Backup and restore

A backup is a single self-contained file:

```text
cd "C:\Program Files\SysWatch\backend"
"C:\Program Files\SysWatch\.venv\Scripts\python.exe" -m app.db.backup C:\ProgramData\SysWatch\backups --keep 7
```

`--keep N` deletes all but the newest N, and only ever deletes files matching
the timestamped name the command itself writes. Retention is off by default.

`VACUUM INTO`, not a file copy, and the difference is not cosmetic. In WAL mode
the database is two files: recent commits live in a `-wal` sidecar until a
checkpoint folds them back. Copying `syswatch.db` alone yields a file missing
whatever had not been checkpointed - silently, and only discovered at restore.

Every backup is verified before the command reports success: an integrity check
and a comparison of the schema revision against the source. A file that fails
is deleted rather than left to be trusted later.

**Backups contain password hashes and session token hashes.** Keep the
directory where `syswatch.env` is kept, not somewhere world-readable.

To restore, stop the backend and the agent, then put the file back:

```text
sc.exe stop SysWatchAgent
copy C:\ProgramData\SysWatch\backups\syswatch-20260904-110137.db C:\ProgramData\SysWatch\syswatch.db
```

Delete any `syswatch.db-wal` and `syswatch.db-shm` beside it first - they
belong to the database you are replacing. Then run `alembic upgrade head`, in
case the backup predates the installed schema, and start the services.

## Reading the service state

```text
sc.exe queryex SysWatchAgent      state and PID
sc.exe qc SysWatchAgent           binary path, start type, account
sc.exe qfailure SysWatchAgent     recovery actions
```

A healthy agent:

```text
STATE              : 4  RUNNING
START_TYPE         : 2  AUTO_START
SERVICE_START_NAME : LocalSystem
BINARY_PATH_NAME   : "C:\Program Files\SysWatch\agent\agent.exe" --service
FAILURE_ACTIONS    : RESTART -- Delay = 5000 milliseconds.
                     RESTART -- Delay = 10000 milliseconds.
                     RESTART -- Delay = 60000 milliseconds.
```

The recovery actions are real: kill `agent.exe` and the SCM restarts it, with a
new PID, within seconds. Three attempts, then the counter resets after a day.

Checking the whole chain:

```text
curl.exe http://127.0.0.1:8080/snapshot     the agent, directly
curl.exe http://127.0.0.1:8000/api/health   the backend is alive
curl.exe http://127.0.0.1:8000/api/ready    the backend can serve
```

`/api/health` answers whether this process responded, which is what a
supervisor needs to decide whether restarting is worth trying. `/api/ready`
answers a different question - is the database there, is the schema current,
can anyone log in - and returns `503` with a body naming what is missing.
Conflating the two makes restarts fix nothing.

## Managing accounts

All from `C:\Program Files\SysWatch\backend`, elevated, with the venv's Python:

```text
python -m app.auth.create_admin                         create the first admin
python -m app.auth.create_admin --username sam --role viewer
python -m app.auth.create_admin --username sam --reset-password
```

There is deliberately **no `--password` flag**. An argument lands in the
shell's history file and in the process list, where it outlives the terminal
session by a long way. The password is only ever read from a hidden prompt.

Resetting a password does not end that user's existing sessions. To do that,
change `SYSWATCH_SESSION_SECRET` - which signs everybody out, not just them.

## What each startup failure means

The backend refuses to start rather than serving traffic in a state it cannot
defend. Each message names the fix.

| Message | Cause | Fix |
| --- | --- | --- |
| `SYSWATCH_SESSION_SECRET must be set when authentication is enabled` | No config file was found, or the key is still commented out | Set `SYSWATCH_CONFIG_FILE`, or uncomment the key in `syswatch.env` |
| `SYSWATCH_SESSION_SECRET must be at least 32 characters` | The key is too short to be a key | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SYSWATCH_AUTH_ENABLED is false, which opens every endpoint and treats every caller as an administrator` | Authentication switched off on a real install | Remove the setting, or set `SYSWATCH_DEV_MODE=true` if this really is a development box |
| `SYSWATCH_CORS_ORIGINS contains '...'. The session cookie is Secure, so a browser on an http:// origin will never send it` | A plain-HTTP origin outside dev mode | Use `https://`, or serve the dashboard from the backend and drop the setting entirely |
| `no such table: users` | Migrations never ran | `alembic upgrade head` |
| `PermissionError: ... syswatch.env` | Not running elevated | The config is Administrators and SYSTEM only, by design |
| Agent: `Could not listen on 127.0.0.1:8080 - is another agent already running?` | Something already holds the port | `sc.exe query SysWatchAgent`, or `netstat -ano \| findstr :8080` |

A failed poll is not a startup failure. The backend runs without the agent; the
stored history stays readable and the poller reports the outage:

```text
WARNING app.services.snapshot_poller: Snapshot poll from http://127.0.0.1:8080
        failed (1 in a row): [WinError 10061] ... actively refused it
```

The first failure carries a traceback; after that the line thins out as the
outage lengthens, and a recovery is logged when polling succeeds again.

## Logs

| File | Written by | Rotation |
| --- | --- | --- |
| `logs\syswatch.log` | the backend | 5 MB, five kept |
| `logs\agent.log` | the agent service | 2 MB, three kept |

Both append across restarts, so the line before a restart is still there, and
both stamp their lines in UTC:

```text
2026-09-06T04:18:16.169Z INFO app.services.snapshot_poller: Polling every 10s
```

That is the same ISO 8601 shape the API serves `collectedAt` in. A log line and
the snapshot it describes name the same instant, spelled the same way, so
correlating them is a string comparison rather than timezone arithmetic - and a
bundle collected from a machine in another timezone still reads against one
clock.

`SYSWATCH_LOG_LEVEL` takes `DEBUG`, `INFO`, `WARNING` or `ERROR`. Successful
per-request chatter is held at `WARNING` deliberately: uvicorn's access log and
httpx's outbound log each write one line per call, and at a ten-second poll
interval that is 8,640 lines a day reporting that the thing that works, worked.

## TLS

SysWatch serves plain HTTP on loopback. That is deliberate and it is not the
whole story:

- The agent binds `127.0.0.1` only and has no authentication. It is reachable
  from the machine it monitors and nowhere else. This is not configurable.
- The backend binds `127.0.0.1` by default. Session cookies carry `Secure`
  outside dev mode, so a browser will only return them over HTTPS or to
  localhost.

To reach it from another machine, put a reverse proxy in front terminating TLS
and forwarding to `127.0.0.1:8000`, and set `SYSWATCH_CORS_ORIGINS` only if the
dashboard is served from somewhere other than the backend. Exposing the backend
directly on a routable address over plain HTTP would send session cookies
across the network in clear.
