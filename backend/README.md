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
alembic upgrade head            # create the database schema
```

The last step is not optional. The application does not create tables on
startup, so without it every poll fails into a logged warning and the
`/snapshots` endpoints stay empty. `alembic upgrade head` also seeds the six
default alert rules.

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
are case-insensitive. There is no `.env` file support.

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
| `SYSWATCH_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Browser origins allowed to call this API |

```bash
SYSWATCH_AGENT_BASE_URL=http://192.168.1.50:8080 python run.py
SYSWATCH_POLL_INTERVAL_SECONDS=60 SYSWATCH_RETENTION_DAYS=90 python run.py
```

`SYSWATCH_CORS_ORIGINS` takes a comma-separated list, not JSON, so it can be set
the way any other shell variable is:

```bash
SYSWATCH_CORS_ORIGINS=http://localhost:5173,http://192.168.1.50:5173 python run.py
```

The two default origins are both spellings of the Vite dev server — a browser
treats `localhost` and `127.0.0.1` as different origins even on the same
machine, so both are listed. Credentials are never allowed regardless of which
origins are configured (see `create_app()`), since the API is unauthenticated
and Phase 4 is where that changes.

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

## API

Interactive documentation is served at `/docs`, with the raw schema at
`/openapi.json`.

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

### `GET /`

Service identity. Returns `200` with `{"service": "syswatch-backend"}`.

### `GET /health`

Liveness check. Returns `200` with `{"status": "ok"}`. Does not contact the
agent, so it stays responsive while the agent is down.

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

**These are the only write endpoints, and they are unauthenticated** — like the
reads. Fine while the backend listens on `127.0.0.1`; it must not reach a
network before Phase 4 adds auth. The CORS config allows `POST`/`PUT`/`DELETE`
only from the configured dashboard origins.

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
        client/       # HTTP client for the C++ agent
        db/           # Engine, session scope, ORM models
        models/       # Pydantic snapshot and alert models
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
