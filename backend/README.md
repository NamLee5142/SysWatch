# SysWatch Backend

FastAPI service that collects system snapshots from the C++ agent, stores them,
and serves both live and historical data as validated, typed JSON.

```text
HTTP client  ->  Python backend (this service)  ->  C++ agent
                 :8000                              :8080
                    |
                    v
                 SQLite
```

A background poller pulls from the agent on an interval and writes each
collection to the database, so history accumulates whether or not anyone is
calling the API. `GET /snapshot` still reads the agent live; the `/snapshots`
endpoints read storage and keep working while the agent is down.

Every endpoint except `GET /health` requires a logged-in session; alert-rule
changes require the `admin` role. See [Authentication](#authentication).

## Requirements

- Python 3.10 or newer (verified on 3.14.2)
- A running SysWatch C++ agent for `/snapshot` and the poller to return data

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux / macOS
pip install -r requirements.txt
alembic upgrade head                    # create the database schema
python -m app.auth.create_admin         # create the first account
```

Neither of the last two steps is optional. The application does not create
tables on startup, so without the migration every poll fails into a logged
warning and the `/snapshots` endpoints stay empty; it also seeds the six
default alert rules. Without an account there is no way to log in, and every
endpoint except `/health` answers `401`.

You will also need a session secret before the process will start — see
[Authentication](#authentication).

## Running

Development, with auto-reload:

```bash
python run.py
```

`run.py` reads `SYSWATCH_HOST` and `SYSWATCH_PORT` and passes `run:app` to
uvicorn as an import string, which is what enables reload.

Explicit uvicorn invocation, or for production (no reload, multiple workers):

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Note that `--host`/`--port` flags override the `SYSWATCH_*` variables, since
uvicorn is being configured directly rather than through `run.py`.

## Running against the real agent

Build the agent, then start it while the backend is running:

```bash
cd agent
cmake --build build
PATH="/c/mingw64/bin:$PATH" ./build/agent.exe    # Git Bash
```

Two things to know:

- **The MinGW runtime must come from the compiling toolchain.** `agent.exe`
  links `libstdc++-6.dll`, `libgcc_s_seh-1.dll` and `libwinpthread-1.dll`
  dynamically. Git Bash ships its own older copies in `/mingw64/bin` that
  shadow the real ones, and the process then fails to start with exit 127 and
  no message. Putting the compiler's `bin` first fixes it. (The
  `-static-libgcc`/`-static-libstdc++` options in `agent/CMakeLists.txt` are
  attached to the `agent_core` static library, which has no link step, so they
  have no effect on the executable.)
- **The agent runs until interrupted.** It collects every 2 seconds and serves
  `/snapshot` until it receives `SIGINT` (Ctrl+C) or `SIGTERM`, then stops the
  collector and the HTTP server before exiting. It previously shut itself down
  after 5 seconds, which made it a demo entrypoint rather than something the
  backend could poll.

Observed behaviour end to end:

| Agent state | `GET /snapshot` |
| --- | --- |
| Not started | `503` |
| Running, snapshot collected | `200` with live data |
| Stopped with Ctrl+C | `503` |

Verified against a real agent on Windows: `processInfo.count` tracks Task
Manager's process count (within a handful, since processes come and go between
the walk and the reading), `processInfo.top` is the ten heaviest by memory, and
`networkInfo.interfaces[].bytes*PerSec` climb under a download and settle
afterwards. `cpuInfo.usagePercent` moves under load, and
`GET /snapshots/series?metric=processes` / `net_recv` return the expected
`count` / `bytes_per_sec` units.

## Configuration

All settings are read from the environment with the `SYSWATCH_` prefix. Names
are case-insensitive.

They can also come from a config file, which is how a service is configured:
a service has no shell to export variables in. The file is found at
`SYSWATCH_CONFIG_FILE`, else `syswatch.env` in `SYSWATCH_DATA_DIR`, else
`syswatch.env` in the working directory. `syswatch.env.example` documents every
setting with real defaults; copy it, do not edit it in place.

Environment variables win over the file, so a one-off override does not need
the file edited.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SYSWATCH_HOST` | `127.0.0.1` | Interface `run.py` binds to |
| `SYSWATCH_PORT` | `8000` | Port `run.py` binds to |
| `SYSWATCH_AGENT_BASE_URL` | `http://127.0.0.1:8080` | Base URL of the C++ agent |
| `SYSWATCH_DATABASE_URL` | `sqlite:///./syswatch.db` | Database the app and migrations both use |
| `SYSWATCH_POLLING_ENABLED` | `true` | Whether the background poller runs |
| `SYSWATCH_POLL_INTERVAL_SECONDS` | `10.0` | Seconds between collections |
| `SYSWATCH_RETENTION_DAYS` | `30` | Age at which snapshots are pruned; `0` keeps them forever |
| `SYSWATCH_ALERTS_ENABLED` | `true` | Whether the poller evaluates alert rules after each successful collection |
| `SYSWATCH_AUTH_ENABLED` | `true` | Master switch for authentication. `false` opens every endpoint |
| `SYSWATCH_SESSION_SECRET` | *(none)* | HMAC key for session tokens. **Required**; startup fails without it |
| `SYSWATCH_SESSION_TTL_SECONDS` | `28800` | Session lifetime from login, absolute |
| `SYSWATCH_DEV_MODE` | `false` | Drops the cookie's `Secure` flag and permits a missing secret |
| `SYSWATCH_CORS_ORIGINS` | *(empty)* | Browser origins allowed to call this API. Empty is right when the backend serves the dashboard |
| `SYSWATCH_CONFIG_FILE` | *(none)* | Path to the config file. Set machine-wide by the installer |
| `SYSWATCH_DATA_DIR` | `%PROGRAMDATA%\SysWatch`, or `./data` in dev mode | Everything else derives from it, so moving this moves the installation |
| `SYSWATCH_LOG_DIR` | `<data dir>\logs` | Where `syswatch.log` is written |
| `SYSWATCH_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. Rotates at 5 MB, five kept |
| `SYSWATCH_DASHBOARD_DIR` | *(none)* | Built dashboard to serve. Unset serves the API only |

```bash
SYSWATCH_AGENT_BASE_URL=http://192.168.1.50:8080 python run.py
SYSWATCH_POLL_INTERVAL_SECONDS=60 SYSWATCH_RETENTION_DAYS=90 python run.py
```

`SYSWATCH_CORS_ORIGINS` takes a comma-separated list, not JSON, so it can be set
the way any other shell variable is:

```bash
SYSWATCH_CORS_ORIGINS=http://localhost:5173,http://192.168.1.50:5173 python run.py
```

The default is empty, and that is usually correct: when this process serves
the dashboard from `SYSWATCH_DASHBOARD_DIR` the two are the same origin, and in
development the Vite dev server proxies `/api` so they are the same origin
there too. Only a dashboard hosted somewhere else needs this set.

Credentials **are** allowed for the configured origins, because the session is
a cookie and the browser would otherwise send it on no cross-origin request.
That is also why `"*"` is refused outright — see [Deployment](#deployment).
Outside dev mode an origin that is not `https://` is refused as well: the
cookie is `Secure`, so a browser on a plain-HTTP origin would never send it
back, and the symptom would be a login that appears to work and then does not.

An invalid value is rejected at startup — a non-numeric `SYSWATCH_PORT` or a
`SYSWATCH_RETENTION_DAYS=forever` raises a `ValidationError` rather than
silently falling back to the default. `SYSWATCH_CORS_ORIGINS` is the one
exception: because `NoDecode` turns off pydantic-settings' usual JSON parsing
for this field, a JSON-array spelling like `SYSWATCH_CORS_ORIGINS=["http://x"]`
is not rejected — it has no commas, so it is read as one literal origin string
(`["http://x"]`, brackets and all) instead of failing to start. The symptom is
the dashboard silently blocked by CORS with nothing in the logs pointing at
why; the fix is always the comma-separated spelling above, never JSON.

`SYSWATCH_DATABASE_URL` is read by both the application and Alembic. The value
in `alembic.ini` is deliberately blank and has no effect, so migrations can
never run against a different database than the app.

The agent request timeout is **not** configurable; it is fixed at 5 seconds in
`AgentClient`.

Set `SYSWATCH_POLLING_ENABLED=false` to serve the API without collecting — for
instance when running a second instance alongside one that already polls, since
two pollers writing the same collections just contend for the same rows.

## Alerts

The agent collects facts; the backend decides whether those facts are an alert.
No threshold, operator or severity ever reaches the agent, so alert policy is
reconfigurable through the API without rebuilding it.

```text
Snapshot ─▶ AlertEngine ─▶ rule evaluation ─▶ alert state ─▶ SQLite ─▶ REST ─▶ Dashboard
              (after a successful poll only)
```

Evaluation runs **only after a successful collection** — never when the agent
was unreachable or the payload was malformed, so infrastructure failure cannot
raise a storm of false alerts. Agent-down stays the responsibility of
`GET /status`.

One firing alert exists per `(rule, host)` at a time: a breach with no open
alert opens one, a breach with an open alert updates it in place (no new row
every tick), and a return to normal resolves it. Disabling or deleting a rule
resolves its open alert on the next tick.

Supported metrics and operators:

| Metric | Unit | Meaning |
| --- | --- | --- |
| `cpu` | percent | `cpuInfo.usagePercent` |
| `memory` | percent | used / total |
| `disk` | percent | **used** percent — "almost full" is `disk gt 90` |
| `processes` | count | `processInfo.count` |
| `net_sent` / `net_recv` | bytes/sec | summed across interfaces |

| Operator | Fires when |
| --- | --- |
| `gt` / `gte` | value `>` / `>=` threshold |
| `lt` / `lte` | value `<` / `<=` threshold |

Six default rules are seeded by migration (CPU > 90 / > 95, memory > 90, disk
> 90, processes > 500, net_recv rate). A rule the user deletes stays deleted —
the seed migration only inserts names that are absent.

## Authentication

Every endpoint except `GET /health` and `GET /` requires a session. The agent
knows nothing about any of this — it stays on loopback with no authentication of
its own, which is exactly why login belongs here.

```text
POST /auth/login ─▶ Argon2id verify ─▶ session row ─▶ Set-Cookie (HttpOnly)
                                                          │
        every later request ◀─────────────────────────────┘
                │
                ▼
   require_authenticated_user ─▶ 401
   require_admin              ─▶ 403
```

### What is stored

A session token is 256 random bits. It is returned once, in the cookie, and
**never written down**: the `sessions` table holds `HMAC-SHA256(secret, token)`.
Someone who reads the database learns which sessions exist but cannot mint a
cookie for any of them, and rotating `SYSWATCH_SESSION_SECRET` invalidates every
live session at once — the lever to pull after a leak.

Passwords are Argon2id (`t=3`, `m=64 MiB`, `p=4`, RFC 9106's first recommended
option), with the parameters pinned rather than left to the library's defaults.
Each hash encodes its own parameters, so raising them later does not invalidate
stored passwords.

### Roles

| | `viewer` | `admin` |
| --- | --- | --- |
| `/status`, `/snapshot(s)`, `/hosts`, `/alerts`, `GET /alert-rules` | ✅ | ✅ |
| `POST` / `PUT` / `DELETE /alert-rules` | `403` | ✅ |

`/health` stays public — it answers one question, is this process alive, and a
load balancer asking it has no session to offer. `/status` does not, because it
reports poll timing, the last error and agent reachability.

### Creating accounts

```bash
python -m app.auth.create_admin                        # prompts for both
python -m app.auth.create_admin --username viv --role viewer
python -m app.auth.create_admin --username root --reset-password
```

A command rather than a `POST /setup-admin` endpoint: an endpoint that mints an
administrator has to be switched off the moment it is first used, and the
version still reachable in production is a well-known way to lose a system.

There is deliberately **no `--password` flag**. The prompt is hidden and the
value never enters shell history or the process list. Passwords must be at least
12 characters and mix two of {lower case, upper case, digits, symbols}.

### What ends a session

- Logging out (`POST /auth/logout`)
- Reaching `expires_at` — absolute, set at login. Activity updates
  `last_seen_at` but does not extend it.
- The account being disabled or deleted, checked on **every** request rather
  than only at login
- `SYSWATCH_SESSION_SECRET` changing

Expired rows are deleted by `SessionService.prune_expired()`; expiry itself is
enforced on read, so the sweep is housekeeping rather than a control.

### Failed logins

`POST /auth/login` answers the same `401` for an unknown username and a wrong
password, and spends the same time on both — an unknown user is verified against
a dummy hash so the response time does not become a username oracle. Ten failures
from one address in five minutes earns a `429` with `Retry-After`; only failures
count, and a success clears the record.

The limiter is in-process: it resets on restart and each worker keeps its own.
That is enough for a single-worker deployment and is not a substitute for one
behind a load balancer.

## Deployment

For installing on a Windows machine - the installer, upgrades, backups,
services, and what each startup failure means - see
[docs/deployment.md](../docs/deployment.md). This section is the reasoning
behind the settings that document uses.

The defaults assume the backend and the dashboard are reached through one origin
and that TLS is terminated in front of this process. Serving the dashboard from
this process (`SYSWATCH_DASHBOARD_DIR`) is the simplest way to get that: one
port, one origin, and the cookie and CORS questions stop existing.

**Run it with `serve.py`, not `run.py`.** `run.py` reloads on every edit, which
is what development wants and what a service manager must never be given.
`serve.py` reads the same settings, does not reload, and refuses `--workers`
with a reason: the poller would run in every worker and collect N times over,
the login rate limit is counted in memory, and SQLite serialises writers.

**Generate a secret.** There is no default, and the process refuses to start
without one:

```bash
export SYSWATCH_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

It must be at least 32 characters. Changing it logs everyone out, which is the
intended emergency response and also the reason not to regenerate it on each
deploy.

**Cookies and origins.** The session cookie is `HttpOnly`, `SameSite=Lax`,
`Secure`, `Path=/`, and carries no `Domain` attribute.

| Deployment | What is needed |
| --- | --- |
| Dashboard and API on one origin (reverse proxy) | Nothing extra. This is the shape the defaults assume. |
| Dashboard on a different origin | Add it to `SYSWATCH_CORS_ORIGINS`, and note that `SameSite=Lax` will not send the cookie on cross-site requests — a same-origin proxy is the supported arrangement. |
| Local development over HTTP | `SYSWATCH_DEV_MODE=true`, which drops `Secure`. The Vite proxy already makes the browser see one origin. |

`SYSWATCH_CORS_ORIGINS` must name explicit origins. `"*"` is rejected at
startup: CORS runs with credentials enabled, and Starlette answers a wildcard
there by echoing back whatever `Origin` asked — which would let any site a
logged-in user visits call this API as them.

**Response headers.** Every response carries `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`. The
documentation UI is exempt from the CSP only — it loads its own scripts. It is
served at `/docs`, outside the `/api` prefix, and is switched off entirely
unless `SYSWATCH_DEV_MODE` is set, so in production there is nothing there to
put behind a proxy.

**Do not expose the agent.** It has no authentication and binds `127.0.0.1` on
purpose. See [the agent README](../agent/README.md#network-exposure).

## Database

Three tables. `snapshots` holds the agent's nested payload flattened into
columns; `alert_rules` and `alerts` back the alert engine.

### `snapshots`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer | Primary key |
| `host_name` | text | From `systemInfo.hostName` |
| `collected_at` | datetime | UTC, stamped by the agent |
| `cpu_core_count` | integer | |
| `cpu_usage_percent` | float | |
| `mem_total_mb` / `mem_used_mb` | integer | |
| `disk_total_gb` / `disk_free_gb` | integer | |
| `os_name` / `os_version` | text | Stored per row: a host's OS version changes over time, so it belongs to the snapshot rather than to the host |
| `process_count` | integer, null | Total running processes; `null` on rows collected before Sprint 7 |
| `net_bytes_sent_per_sec` / `net_bytes_recv_per_sec` | float, null | Throughput summed across interfaces |
| `process_top` | JSON, null | The heaviest processes by memory — point-in-time detail, read only from the latest row |
| `network_interfaces` | JSON, null | Per-interface breakdown — likewise latest-only |

The last five columns are nullable and were added in Sprint 7. The three
scalars are what `GET /snapshots/series` buckets; the two JSON columns are
carried on every row but only ever read back from `GET /snapshots/latest`.

Two constraints do real work:

- **`uq_snapshots_host_name_collected_at`** makes collection idempotent. The
  poller re-reads the agent's *latest* snapshot every tick, so whenever it polls
  faster than the agent collects it sees the same snapshot again. The unique
  constraint collapses those repeats instead of filling the table with
  duplicates.
- **`ix_snapshots_collected_at`** serves queries that do not filter by host —
  cross-host history and retention pruning — which the host-leading unique index
  cannot answer.

Times are stored as **naive UTC**, because SQLite has no timezone type and would
otherwise return a value stripped of its offset. `SnapshotStore` converts on the
way in and re-tags on the way out, so callers only ever see UTC-aware datetimes.

### `alert_rules`

`id`, `name`, `metric`, `operator`, `threshold`, `severity`
(`info` / `warning` / `critical`), `enabled`, `created_at`, `updated_at`.
`metric` and `operator` are plain text, so a new one needs no schema change.

### `alerts`

`id`, `rule_id` (nullable FK → `alert_rules.id`, `ON DELETE SET NULL`),
`host_name`, `state` (`firing` / `ok`), `value`, `triggered_at`, `resolved_at`,
`last_seen_at`, plus a **copy** of the rule's `rule_name` / `metric` /
`operator` / `threshold` / `severity` taken when the alert opens. The copy is
what keeps a past alert truthful after its rule is edited or deleted — the same
reasoning that keeps `os_version` on the snapshot.

`PRAGMA foreign_keys=ON` is set per connection so the `ON DELETE SET NULL`
actually fires (SQLite ignores foreign keys otherwise).

### `users`

`id`, `username` (unique), `password_hash` (Argon2id), `role`
(`admin` / `viewer`), `enabled`, `created_at`, `updated_at`.

### `sessions`

`id`, `token_hash` (unique — `HMAC-SHA256` of the cookie value, never the value
itself), `user_id` (FK → `users.id`, `ON DELETE CASCADE`), `expires_at`,
`created_at`, `last_seen_at`.

The cascade matters: a session that resolves to nobody would be a row the auth
dependency has to defend against for no reason.

### Migrations

```bash
alembic upgrade head            # apply
alembic downgrade base          # drop everything
alembic revision --autogenerate -m "describe the change"
alembic check                   # fail if models and migrations have diverged
```

Batch mode is enabled for SQLite, which cannot `ALTER` most things in place, and
every constraint is named through a metadata naming convention — SQLite cannot
alter a constraint it cannot name.

### Retention

The poller prunes snapshots older than `SYSWATCH_RETENTION_DAYS`, at most once
an hour rather than on every tick. Pruning failures are logged and swallowed:
housekeeping must never be the reason collection stops.

### Running the suite against PostgreSQL

SQLite is what ships and what is supported. PostgreSQL is a **test target**: one
CI job runs the whole suite against it, to keep "the repository layer is the
storage boundary" an executed claim rather than a comment. Nothing that ships
opens a PostgreSQL connection, and `deploy/` cannot install one.

```bash
docker run -d --name syswatch-pg -p 55432:5432     -e POSTGRES_PASSWORD=syswatch -e POSTGRES_DB=syswatch postgres:16
pip install "psycopg[binary]"
SYSWATCH_TEST_DATABASE_URL=postgresql+psycopg://postgres:syswatch@127.0.0.1:55432/syswatch pytest
```

`SYSWATCH_TEST_DATABASE_URL` is read by `conftest.py` and by nothing else - it
is not a setting, and `SYSWATCH_DATABASE_URL` remains what the application
reads. Six test modules keep their own SQLite engines on purpose and are
unaffected by it: they are about SQLite itself (the pragmas in `db/session.py`,
`VACUUM INTO` in `db/backup.py`), or they need a file-backed database to put
real threads on separate connections.

The CI container is deliberately **not** set to UTC. Timestamps are stored as
naive UTC, which SQLite has no choice about; a server supplies the offset its
session timezone implies, so on a UTC server correct and incorrect code look
identical. `_configure_postgresql` pins every connection to UTC for the same
reason `_configure_sqlite` sets the pragmas, and a container seven hours off is
what proves it is still there.

What stays SQLite-only, by design rather than by omission:

| | |
| --- | --- |
| `db/backup.py` | `VACUUM INTO`. Refuses a non-SQLite URL outright rather than producing something that is not a backup. |
| `db/session.py` pragmas | WAL, `busy_timeout`, `foreign_keys`. All three are answers to SQLite problems a server does not have. |
| Migrations | Alembic runs against SQLite only, here and in `deploy/`. Batch mode and the naming convention exist because SQLite cannot `ALTER` in place. The PostgreSQL job builds its schema from the models with `create_all`, so the migration chain is **not** exercised against it. |
| One test | `test_collected_at_reads_back_without_a_timezone`, marked `sqlite_only`. It asserts that the offset is dropped, which is why `to_storage_time` exists. |

## API

**Every endpoint below is under `/api`.** `GET /health` is served at
`/api/health`, and so on. The prefix exists because this process also serves
the dashboard, whose client-side routes include `/alerts` — without it a deep
link to the alerts page and the alerts endpoint are the same URL, and one of
them has to lose.

Interactive documentation is served at `/docs`, with the raw schema at
`/openapi.json`. Those two are *not* under the prefix - they belong to the
application rather than to a router. Both are switched off unless
`SYSWATCH_DEV_MODE` is set, and answer `404` otherwise: they are a development
tool, and in production a free, always-current map of every endpoint and
request shape offered to anyone who can reach the port.

| Endpoint | Source | While the agent is down |
| --- | --- | --- |
| `GET /snapshot` | Agent, live | `503` |
| `GET /snapshots` | Database | Still works |
| `GET /snapshots/latest` | Database | Still works |
| `GET /snapshots/series` | Database | Still works |
| `GET /status` | Backend + poller state | `200`, reports `agent: "down"` |
| `GET /hosts` | Database | Still works |
| `GET /alerts`, `/alerts/active`, `/alerts/{id}` | Database | Still works |
| `GET`/`POST`/`PUT`/`DELETE /alert-rules` | Database | Still works |
| `POST /auth/login`, `/auth/logout`, `GET /auth/me` | Database | Still works |
| `GET /ready` | Database | Still works; reports what is missing |

Everything above except `GET /health`, `GET /ready` and `GET /` requires a
session; the
three alert-rule writes additionally require the `admin` role. See
[Authentication](#authentication).

### `GET /`

Service identity. Returns `200` with `{"service": "syswatch-backend"}`.

### `GET /health`

Liveness check. Returns `200` with `{"status": "ok", "version": "0.10.0"}`. The
body is a literal - it contacts nothing - so it stays responsive while the
agent is down, and answers the one question a supervisor needs: did this
process respond. The version rides along because this is the endpoint a
deployment check already calls, and "which build is running" is the next thing
asked after "is it up".

### `GET /ready`

Readiness check, and a different question from liveness: is the database
reachable, is the schema at the revision this build expects, does any account
exist to log in with.

```json
{
  "status": "ready",
  "checks": {"database": "ok", "schema": "ok", "accounts": "ok"}
}
```

Returns `503` when it is not, with the same shape and the failing check
replaced by what is missing, as an instruction rather than a stack trace:

```json
{
  "status": "not ready",
  "checks": {
    "database": "ok",
    "schema": "the schema is not initialised; run 'alembic upgrade head'",
    "accounts": "no accounts exist; run 'python -m app.auth.create_admin'"
  }
}
```

Unauthenticated, because a supervisor has no session, and a readiness check
that needs one cannot be used before anybody has logged in.

Conflating this with `/health` makes restarts fix nothing: a process that is
running perfectly against an unmigrated database is alive and not ready, and
restarting it will not migrate anything.

### `GET /snapshot`

Fetches the latest snapshot from the agent and returns it as a typed model.

```json
{
  "collectedAt": "2026-08-12T11:15:27Z",
  "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
  "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
  "diskInfo": {"totalGB": 512, "freeGB": 120},
  "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"},
  "processInfo": {
    "count": 240,
    "top": [{"pid": 1234, "name": "chrome.exe", "memoryMB": 512}]
  },
  "networkInfo": {
    "interfaces": [
      {"name": "Wi-Fi", "bytesSent": 1000, "bytesRecv": 2000,
       "bytesSentPerSec": 30.0, "bytesRecvPerSec": 90.0}
    ]
  }
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `collectedAt` | datetime | ISO-8601 UTC, stamped by the agent at collection time |
| `cpuInfo.coreCount` | int | Logical cores |
| `cpuInfo.usagePercent` | float | 0–100 |
| `memoryInfo.totalMB` / `usedMB` | int | Megabytes |
| `diskInfo.totalGB` / `freeGB` | int | Gigabytes |
| `systemInfo.name` / `version` / `hostName` | string | OS identity |
| `processInfo.count` | int | Total running processes |
| `processInfo.top[]` | object | The heaviest 10 by memory — `pid`, `name`, `memoryMB` |
| `networkInfo.interfaces[]` | object | One per operational, non-loopback interface — cumulative `bytesSent` / `bytesRecv` plus the agent-derived `bytesSentPerSec` / `bytesRecvPerSec` |

`processInfo` and `networkInfo` are **omitted** (not `null`) when the agent that
produced the snapshot predates Sprint 7. An agent with no active network
interface sends `"networkInfo": {"interfaces": []}`.

Status codes:

| Code | Meaning | Cause |
| --- | --- | --- |
| `200` | Snapshot returned | Agent replied `200` with a valid payload |
| `404` | No snapshot available yet | Agent replied `204` — it has not collected one |
| `502` | Bad agent response | Agent replied with an unexpected status, malformed JSON, or a payload failing validation |
| `503` | Unable to reach agent | Connection refused, timed out, or otherwise unreachable |

Errors use FastAPI's standard shape:

```json
{"detail": "Unable to reach agent"}
```

### `GET /snapshots`

Stored snapshots, newest first. Never contacts the agent.

```bash
curl "http://127.0.0.1:8000/snapshots?host=devbox&limit=50"
curl "http://127.0.0.1:8000/snapshots?since=2026-08-12T00:00:00Z&until=2026-08-13T00:00:00Z"
```

```json
{
  "items": [
    {
      "collectedAt": "2026-08-12T11:15:27Z",
      "cpuInfo": {"coreCount": 8, "usagePercent": 42.5},
      "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
      "diskInfo": {"totalGB": 512, "freeGB": 120},
      "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"}
    }
  ],
  "count": 137
}
```

Items use the same nested shape as `GET /snapshot`, so one parser handles both
live and historical data — including `processInfo` and `networkInfo`, rebuilt
from the stored columns and omitted for rows that predate Sprint 7.

| Parameter | Default | Notes |
| --- | --- | --- |
| `host` | all hosts | Exact host name |
| `since` | unbounded | Earliest collection time, inclusive |
| `until` | unbounded | Latest collection time, inclusive |
| `limit` | `100` | 1–1000; out of range is a `422`, not a silent clamp |
| `offset` | `0` | Rows to skip |

`count` is the **total** matching rows, ignoring `limit` and `offset`, so a
caller holding one page can tell whether more exist.

Timestamps may be given with or without an offset; a naive value is read as UTC.
A window where `since` is after `until` returns `422`.

### `GET /snapshots/series`

Bucketed averages for one metric, oldest first — built for charting, where
`GET /snapshots` (newest-first, one row per collection) would mean the client
reverses and averages the data itself.

```bash
curl "http://127.0.0.1:8000/snapshots/series?metric=cpu&since=2026-08-12T00:00:00Z&bucket=hour"
```

```json
{
  "metric": "cpu",
  "bucket": "hour",
  "unit": "percent",
  "points": [
    {"t": "2026-08-12T00:00:00Z", "value": 42.5},
    {"t": "2026-08-12T01:00:00Z", "value": 38.1}
  ]
}
```

| Parameter | Default | Notes |
| --- | --- | --- |
| `metric` | required | `cpu`, `memory`, `disk`, `processes`, `net_sent` or `net_recv` |
| `host` | all hosts | Exact host name |
| `since` | unbounded | Earliest collection time, inclusive |
| `until` | unbounded | Latest collection time, inclusive |
| `bucket` | `hour` | `raw`, `minute`, `hour` or `day` — the averaging window, or every sample for `raw` |

`unit` says what `points[].value` is measured in — `percent` for `cpu` /
`memory` / `disk` (one shared 0-100 axis), `count` for `processes`,
`bytes_per_sec` for `net_sent` / `net_recv`. A client labels the axis from
`unit` rather than assuming a percentage. Buckets whose rows never carried the
requested metric (any row collected before Sprint 7, for `processes` and the
network metrics) contribute no point rather than a zero.

Points are **oldest first**, the opposite order from `GET /snapshots` — a chart
is read left to right, and reversing one silently flips its axis.

A window whose point count would exceed 5000 returns `422` rather than being
silently truncated, since a truncated chart draws a range that did not happen.
Narrow the window or pick a coarser bucket.

### `GET /snapshots/latest`

The most recently stored snapshot, in the same shape as `GET /snapshot`. Takes
an optional `host` parameter. Returns `404` with `"No snapshot stored yet"` when
nothing matches.

This is the endpoint to fall back to when `GET /snapshot` returns `503` — it
serves the last known state from storage rather than failing.

### `GET /status`

Whether the backend is reaching the agent — always `200`, even when it is not.
A dashboard needs to tell "the agent is unreachable" apart from "the backend
itself is unreachable", and a non-2xx response here could not make that
distinction.

```json
{
  "backend": "ok",
  "agent": "up",
  "pollerRunning": true,
  "lastPollAt": "2026-08-12T11:15:30Z",
  "lastSuccessAt": "2026-08-12T11:15:30Z",
  "lastPollError": null
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `backend` | `"ok"` | Constant; this process answered the request |
| `agent` | `"up"` \| `"down"` \| `"unknown"` | See below |
| `pollerRunning` | bool | `false` when `SYSWATCH_POLLING_ENABLED=false` |
| `lastPollAt` | datetime or `null` | When the poller last completed a tick, successful or not |
| `lastSuccessAt` | datetime or `null` | When a snapshot last actually arrived — diverges from `lastPollAt` while the agent is down |
| `lastPollError` | string or `null` | The most recent poll failure, if any |

`agent` is `"unknown"` rather than `"down"` before the poller's first tick
lands, or whenever polling is disabled — reporting "down" in either case would
put a red light on a dashboard watching a perfectly healthy agent nobody has
asked about yet. It only becomes `"up"` or `"down"` once at least one poll has
completed.

### `GET /hosts`

Every host that has stored at least one snapshot, most recently active first.
Never contacts the agent.

```json
{
  "items": [
    {"hostName": "devbox", "lastCollectedAt": "2026-08-12T11:15:27Z", "snapshotCount": 4213}
  ]
}
```

An empty `items` list is a `200`, not a `404` — a fresh database is a valid
state, and the dashboard renders an empty selector rather than an error page
for it.

### `GET /alerts`

Alert history, newest first. `{"items": [...], "count": n}`, where `count` is
the total ignoring paging. Filters: `host`, `state` (`firing` / `ok`),
`rule_id`, `since`, `until` (on `triggered_at`), `limit` (1–1000), `offset`. A
window with `since` after `until` is a `422`.

Each alert carries the copied rule fields (`ruleName`, `metric`, `operator`,
`threshold`, `severity`) alongside `ruleId` (which is `null` once the rule is
deleted), `hostName`, `state`, `value`, `triggeredAt`, `resolvedAt`,
`lastSeenAt`.

### `GET /alerts/active`

Just the firing alerts, newest `triggeredAt` first. `{"items": [...]}` — no
`count`, there are never many. Optional `host` filter.

### `GET /alerts/{id}`

One alert. `404` when the id is unknown.

### `GET /alert-rules`

Every configured rule, newest first. `{"items": [...]}`.

### `POST /alert-rules`

Create a rule. `201` with the stored rule. Body:

```json
{"name": "CPU critical", "metric": "cpu", "operator": "gt", "threshold": 95,
 "severity": "critical", "enabled": true}
```

`severity` defaults to `warning`, `enabled` to `true`. A blank name, an unknown
metric or operator, or a non-finite threshold is a `422`.

### `PUT /alert-rules/{id}`

Partial update — send only the fields to change; at least one is required.
`404` for an unknown id, `422` for an invalid value.

### `DELETE /alert-rules/{id}`

`204`. `404` for an unknown id. Open alerts for the rule survive as history with
`ruleId` set to `null`.

These three are the only write endpoints, and the only ones that require the
`admin` role. Reading rules is open to any authenticated caller.

## Testing

```bash
cd backend
python -m pytest          # whole suite
python -m pytest -v       # per-test names
```

`conftest.py` puts `backend/` on `sys.path`, so pytest must be run from this
directory.

The suite covers the models, `AgentClient`, `SnapshotService`, the API layer,
configuration loading, the database layer (engine, ORM models, migrations,
`SnapshotStore`, `AlertRuleStore`, `AlertStore`), the poller, the alert
evaluator and engine (including the full state machine against a real
database), and an end-to-end pass through the real stack with only the agent's
HTTP transport stubbed (`tests/test_snapshot_integration.py`).

Every test that touches the database uses an in-memory or temporary SQLite file,
so running the suite never writes to `syswatch.db`.

`conftest.py` runs the suite with `SYSWATCH_AUTH_ENABLED=false` unless a test
asks for one of the `anon_client` / `viewer_client` / `admin_client` fixtures.
The routes still run their real dependency chain — it resolves to an anonymous
admin — which keeps the several hundred tests about snapshots and alerts from
each having to arrange a login. Authentication and authorization have their own
files (`test_auth_*.py`, `test_authorization.py`) that use the real thing.

Run the suite with the agent **stopped**. No test needs it running, but
`test_get_snapshot_connection_error` opens a real socket to
`127.0.0.1:8080` and asserts the connection fails, so it reports a false
failure if an agent happens to be listening there.

## Dependencies

Pins are exact, and pydantic is on v2. Pinning back to v1 is not a free choice:
FastAPI stopped working with pydantic v1 at 0.120.0 while still advertising
`pydantic>=1.7.4` in its metadata, so a v1 pin resolves cleanly and then fails
at import. Staying on v1 would cap FastAPI at 0.118.0 with nothing to stop an
upgrade from breaking the app.

## Structure

```text
backend/
    alembic/          # Migration environment and versions
    app/
        alerts/       # Rule evaluator and alert engine (no SQLAlchemy)
        api/          # FastAPI routes
        auth/         # Passwords, sessions, dependencies, rate limit, admin CLI
        client/       # HTTP client for the C++ agent
        db/           # Engine, session scope, ORM models
        models/       # Pydantic snapshot, alert and auth models
        repositories/ # SnapshotStore / AlertRuleStore / AlertStore — the persistence boundary
        services/     # Snapshot service and background poller
    tests/
    alembic.ini       # Migration config; its database URL is intentionally blank
    config.py         # Settings, read from SYSWATCH_ env vars
    conftest.py       # Puts backend/ on sys.path for pytest
    run.py            # Development entrypoint
```

SQLAlchemy appears only under `app/db/` and `app/repositories/`. Services and
routes work with `SnapshotStore`, which is what keeps a future move to
PostgreSQL a change of configuration and one layer rather than a rewrite.
