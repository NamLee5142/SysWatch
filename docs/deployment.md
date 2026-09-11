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
    syswatch.env                    configuration: the session secret, and
                                    the agent's token if this machine pushes
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
| `-BackendUrl` | *(none)* | Report to a backend on another machine. See [Monitoring a second machine](#monitoring-a-second-machine) |
| `-AgentToken` | *(none)* | The credential that goes with it. Both, or neither |
| `-AllowInsecurePush` | off | Required to push over plain HTTP to anywhere but this machine |

### After installing: open a new terminal

The installer sets `SYSWATCH_CONFIG_FILE` as a **machine** environment
variable, and `SYSWATCH_AGENT_CONFIG_FILE` beside it - the same path, because
the agent and the backend read the same file. Windows hands those to processes
started afterwards, so services get them, but the terminal you ran the
installer from does not - it inherited its environment before the variables
existed.

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

## Monitoring a second machine

One backend, many machines. The first machine runs a backend that polls the
agent beside it on loopback; every machine after that runs an agent which
**pushes** its snapshots to that backend instead.

The direction is the point. The agent has no authentication of its own and
binds `127.0.0.1` only, so it can never be polled across a network - see
[decisions/0001](decisions/0001-agents-push-to-the-backend.md). Pushing means
the monitored machine opens an outbound connection and nothing new listens.

```text
  backend machine                     second machine
  +---------------------+             +---------------------+
  | agent  127.0.0.1 <--+-- polled    | agent               |
  | backend :8000 <-----+-------------+-- pushes            |
  | dashboard           |   POST      +---------------------+
  +---------------------+   /api/ingest/snapshot
                            Authorization: Bearer <token>
```

### Before you start: the backend has to be reachable

The backend binds `127.0.0.1` by default, so nothing outside its own machine
can reach it. That is the first thing to fix, and it is a decision about
exposure rather than a setting to flip without thinking:

- **A reverse proxy in front**, forwarding to `127.0.0.1:8000`. This is the
  right answer, and the one that also gives the dashboard TLS.
- **Or `SYSWATCH_HOST=0.0.0.0`** in `syswatch.env`, which puts the backend
  itself on the network. Only sane on a trusted segment: session cookies would
  then cross it in clear.

Whichever you choose, the address the agent is given must be the **full ingest
endpoint** - `http://backend:8000/api/ingest/snapshot`, not just the host.

### 1. Issue a token, on the backend machine

From an **elevated** prompt, in the install's backend directory:

```text
cd "C:\Program Files\SysWatch\backend"
..\.venv\Scripts\python.exe -m app.auth.create_agent_token --host buildbox --description "shop floor PC"
```

```text
Agent token 1 issued for 'buildbox'.

hS9Xq2N_p0LmVt7ZcJ4YbRdE1oKgAu3WxFiT6vQnMzs

Shown once. It is stored as a hash, so this cannot be recovered - issue a new
one if it is lost.
Put it in the agent's configuration on that machine, in a file only
Administrators and SYSTEM can read.
```

`--host` is the name the machine will appear under in the dashboard. **It is
the host identity**: snapshots are filed under the name the token carries, not
under the hostname inside the payload, so one compromised agent cannot write
another machine's history. It does not have to match the machine's real
hostname, but it will confuse whoever reads it in a year if it does not.

There is deliberately no `--token` flag to supply your own. An argument like
that lands in the shell's history file and in the process list, where it
outlives the terminal by a long way.

### 2. Install on the second machine with it

From an **elevated** prompt on the new machine:

```text
powershell -ExecutionPolicy Bypass -File deploy\Install-SysWatch.ps1 `
    -BackendUrl http://backend:8000/api/ingest/snapshot `
    -AgentToken hS9Xq2N_p0LmVt7ZcJ4YbRdE1oKgAu3WxFiT6vQnMzs `
    -AllowInsecurePush
```

The two go together: a URL with no token is refused, and so is a token with no
URL. They are written into `syswatch.env` on that machine, which the installer
restricts to Administrators and SYSTEM.

`-AllowInsecurePush` is required because the agent speaks no TLS yet, so the
token crosses the network in clear on every push. The installer refuses without
it rather than warning, because a warning is read once and the token is sent on
every collection - every two seconds, by default. See [TLS](#tls) below, and
[decisions/0002](decisions/0002-the-agent-speaks-tls-through-winhttp.md) for
when this goes away.

Add `-SkipAdminAccount` too, unless you want the account prompt: the second
machine gets its own backend, and an account on it logs into nothing you would
use.

**That second backend and dashboard are not needed.** There is no agent-only
install today: the script installs all three components, and the local backend
polls the local agent as well. It is harmless - that machine's data reaches the
real backend either way - but it is a service and a port doing nothing useful.
Stop and disable it if you would rather not have it:

```text
sc.exe config SysWatchBackend start= disabled
sc.exe stop SysWatchBackend
```

### 3. Check it arrived

Three places, in increasing order of effort:

- **The dashboard.** The host selector on the backend machine gains the new
  name within a collection interval or two.
- **The token's last-seen time**, on the backend machine:

  ```text
  ..\.venv\Scripts\python.exe -m app.auth.create_agent_token --list
  ```

  ```text
    ID  HOST                     STATE    LAST SEEN              DESCRIPTION
     1  buildbox                 enabled  2026-09-09T08:14:02    shop floor PC
  ```

  `never` means nothing has arrived with that token yet.
- **`agent.log` on the second machine**, at
  `C:\ProgramData\SysWatch\logs\agent.log`. A working agent logs
  `Pushing snapshots to <url>` once at startup. A broken one says why:

  | Line | Means |
  | --- | --- |
  | `Refusing to push to ... over plain HTTP` | `-AllowInsecurePush` was not set |
  | `A backend URL is configured but no token is` | The token key is missing from `syswatch.env` |
  | `The backend URL is https, which this agent cannot speak` | Not yet - see [TLS](#tls) |
  | `Could not push a snapshot (N in a row, M held)` | The backend is unreachable. Snapshots are held, not lost |
  | `401` on every push | The token is revoked, or was issued under a different `SYSWATCH_SESSION_SECRET` |

An unreachable backend is buffered, not dropped: the agent holds the most
recent 512 snapshots and sends them when the backend comes back. A restart
loses the buffer - it is memory, not a spool file.

### Rotating and revoking

A host may hold more than one enabled token at a time, which is what makes
rotation possible without a gap:

```text
python -m app.auth.create_agent_token --host buildbox      # issue the new one
                                                           # deploy it, then:
python -m app.auth.create_agent_token --revoke 1           # disable the old one
```

Revoking is a flag on the row, not a delete, so the record of what existed
survives. `--restore <id>` undoes it.

Revoking every token for a host does not remove its history; the snapshots
stay. `SYSWATCH_SESSION_SECRET` is the bigger lever - the tokens are HMACs
under it, so changing it invalidates every agent token at once, along with
every session.

### Upgrading a pushing machine

Run the installer again with no push parameters and the existing settings are
kept:

```text
    Keeping the existing session secret.
    Keeping the existing push configuration.
```

Passing `-BackendUrl` and `-AgentToken` again replaces them as a pair. There is
no way to change only the URL - that is deliberate, so that re-pointing a
machine cannot silently send an existing credential to a new host.

To stop a machine pushing, remove the three `SYSWATCH_AGENT_*` lines from its
`syswatch.env` and restart `SysWatchAgent`. The agent goes back to serving
loopback only.

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

## Alert delivery

Alerts are always recorded and always written to `syswatch.log`. Telling
somebody is separate, off by default, and configured here. Everything below
goes in `syswatch.env` (`%PROGRAMDATA%\SysWatch\syswatch.env`), which is
readable by Administrators and SYSTEM only, so it is the right place for a
mailbox password. Restart the backend service after editing it.

### Mail

```ini
SYSWATCH_SMTP_HOST=smtp.example.com
SYSWATCH_SMTP_PORT=587
SYSWATCH_SMTP_FROM=syswatch@example.com
SYSWATCH_SMTP_TO=ops@example.com,oncall@example.com
SYSWATCH_SMTP_USERNAME=syswatch@example.com
SYSWATCH_SMTP_PASSWORD=...
```

`HOST`, `FROM` and `TO` are required together — setting one and not the others
is refused at startup rather than discovered when an alert does not arrive.
`USERNAME` and `PASSWORD` are optional, and must be set together or not at all:
a username with no password authenticates as nobody, and a password with no
username is a secret sitting in a file for no reason.

`SYSWATCH_SMTP_TO` is comma-separated, not JSON, like `SYSWATCH_CORS_ORIGINS`.

**Credentials are never sent over an unencrypted connection.** The client
issues `STARTTLS` when the server offers it. If the server does not offer it
and a username is configured, the send fails with

```text
smtp.example.com does not offer STARTTLS and credentials are configured;
refusing to send the password in clear
```

That is deliberate, and not a bug to work around: an alert that did not arrive
is a far better outcome than a mailbox password on the network. A server with
no `STARTTLS` and no credentials configured is allowed, because there is
nothing to protect.

Port 587 is the default and is the submission port that expects `STARTTLS`.
Implicit TLS on port 465 is not supported.

### Webhook

```ini
SYSWATCH_WEBHOOK_URL=https://hooks.example.com/services/T000/B000/XXXX
```

A single `POST` per state change:

```json
{"change": "opened", "alert": {"id": 12, "ruleName": "CPU usage critical",
 "hostName": "devbox", "severity": "critical", "value": 97.4,
 "triggeredAt": "2026-09-06T04:18:16.169Z", "...": "..."}}
```

`change` is `opened` or `resolved`. Anything that accepts a JSON `POST` works;
Slack, Discord and Teams all need a small forwarder to reshape the body, which
is why there is no native integration for any of them.

**Treat the URL as a credential.** Slack, Discord and Teams all put a token in
the path. It is why `app/alerts/webhook.py` contains no logger at all, why the
failure message says `the webhook answered 401` rather than quoting the URL,
and why `httpx` is held at `WARNING` in `logging_config.py` — `httpx` logs the
full URL of every request it makes, so lowering that level publishes the token
into `syswatch.log`.

Prefer `https://`. An `http://` URL is accepted with a warning at startup,
because the alert contents and any token in the path cross the network in
clear.

### Which alerts get sent

```ini
SYSWATCH_NOTIFY_MIN_SEVERITY=warning
SYSWATCH_NOTIFY_REPEAT_HOURS=0
```

`MIN_SEVERITY` applies to mail and webhooks only — the log records everything
regardless, so nothing is lost, it just is not sent.

`ALERT_RESOLVE_AFTER_SECONDS` is why a recovery arrives a couple of minutes
after the metric drops: an alert closes only once the value has stayed under
its threshold for that long. Without it a rule at 90% and a machine hovering
there sends an opened-and-resolved pair every time the number crosses the line -
measured at five pairs in three minutes on a real run.

`REPEAT_HOURS` is `0` by default, meaning an alert is announced once when it
opens and once when it resolves. Setting it to `4` re-sends a still-firing
alert every four hours until somebody acknowledges it or the condition clears.
Acknowledging an alert stops its reminders; silencing a rule stops everything
for that rule until the silence expires. Both are done from the dashboard's
Alerts page.

### Checking it works

There is no test-message command. The quickest real check is a rule that
cannot help firing:

```powershell
# A rule that fires on the next poll, at most ten seconds away.
curl.exe -X POST http://127.0.0.1:8000/api/alert-rules -H "Content-Type: application/json" `
    -b cookies.txt -d '{\"name\":\"delivery test\",\"metric\":\"cpu\",\"operator\":\"gte\",\"threshold\":0,\"severity\":\"critical\"}'
```

Watch `syswatch.log`; the log transport always runs, so a line there with no
mail arriving separates "the alert did not fire" from "the transport failed".
Delete the rule afterwards.

### When delivery fails

A failed delivery never stops anything. Each transport is isolated, so a broken
webhook does not stop the mail, and neither stops the poller collecting:

```text
WARNING app.alerts.notifier: Could not deliver an alert through smtp
```

The alert is still recorded, still visible in the dashboard, and still marked
as notified — otherwise a dead mail server turns a reminder into a retry loop
against a server that is already down.

Delivery runs on the poll path, so a transport that hangs delays the next
collection. Both transports time out after 10 seconds for that reason. A
refused connection is fast rather than free: 2.06 s measured on Windows
loopback, paid once per state change.

## What each startup failure means

The backend refuses to start rather than serving traffic in a state it cannot
defend. Each message names the fix.

| Message | Cause | Fix |
| --- | --- | --- |
| `SYSWATCH_SESSION_SECRET must be set when authentication is enabled` | No config file was found, or the key is still commented out | Set `SYSWATCH_CONFIG_FILE`, or uncomment the key in `syswatch.env` |
| `SYSWATCH_SESSION_SECRET must be at least 32 characters` | The key is too short to be a key | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `SYSWATCH_AUTH_ENABLED is false, which opens every endpoint and treats every caller as an administrator` | Authentication switched off on a real install | Remove the setting, or set `SYSWATCH_DEV_MODE=true` if this really is a development box |
| `SYSWATCH_CORS_ORIGINS contains '...'. The session cookie is Secure, so a browser on an http:// origin will never send it` | A plain-HTTP origin outside dev mode | Use `https://`, or serve the dashboard from the backend and drop the setting entirely |
| `Mail is half configured: ... set, ... missing` | Some of `SMTP_HOST` / `SMTP_FROM` / `SMTP_TO` but not all | Set the rest, or unset all three |
| `SYSWATCH_SMTP_USERNAME and SYSWATCH_SMTP_PASSWORD must be set together, or neither` | One without the other | Set both to authenticate, or neither for an open relay |
| `SYSWATCH_WEBHOOK_URL is not an http:// or https:// URL` | A typo, or a host with no scheme | Give a full URL. The value is never quoted back in the message, because it is usually a credential |
| `no such table: users` | Migrations never ran | `alembic upgrade head` |
| `PermissionError: ... syswatch.env` | Not running elevated | The config is Administrators and SYSTEM only, by design |
| Agent: `Could not listen on 127.0.0.1:8080 - is another agent already running?` | Something already holds the port | `sc.exe query SysWatchAgent`, or `netstat -ano \| findstr :8080` |

Two notification problems are warnings rather than refusals, because both
still deliver something:

```text
WARNING: SYSWATCH_WEBHOOK_URL is http://: alert contents, and the token in the
         URL if it has one, cross the network in clear.
WARNING: No alert transport is configured: alerts are recorded and logged, and
         nobody is told.
```

The second is the default state of a fresh install, and is worth seeing once so
that it is a choice.

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
  from the machine it monitors and nowhere else. This is not configurable, and
  monitoring a second machine will not change it - see
  [decisions/0001](decisions/0001-agents-push-to-the-backend.md), which settles
  that agents will push to the backend rather than be polled across a network.
- The backend binds `127.0.0.1` by default. Session cookies carry `Secure`
  outside dev mode, so a browser will only return them over HTTPS or to
  localhost.
- **A pushing agent speaks plain HTTP, and cannot yet do otherwise.** Its HTTP
  client is hand-rolled on Winsock and has no TLS in it, so
  `-AllowInsecurePush` is currently the only way to monitor a second machine.
  The token, and the process names, interfaces and OS version in every push,
  cross the network readable.

To reach it from another machine, put a reverse proxy in front terminating TLS
and forwarding to `127.0.0.1:8000`, and set `SYSWATCH_CORS_ORIGINS` only if the
dashboard is served from somewhere other than the backend. Exposing the backend
directly on a routable address over plain HTTP would send session cookies
across the network in clear.

That leaves a gap today: browsers can be given TLS, agents cannot, so a
multi-machine deployment needs a network segment you would be willing to send
a credential across. It is a stopgap with an end date rather than a position -
[decisions/0002](decisions/0002-the-agent-speaks-tls-through-winhttp.md)
settles that the agent moves to WinHTTP and `https://`, and
[sprint-13](sprint-13.md) removes `allowInsecurePush` entirely in the sprint
that makes it unnecessary.
