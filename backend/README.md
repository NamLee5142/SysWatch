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
`/snapshots` endpoints stay empty.

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

Note that `cpuInfo.usagePercent` is currently always `0.0` — it is a
placeholder in the agent's `CPUCollector`, not a measurement.

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

```bash
SYSWATCH_AGENT_BASE_URL=http://192.168.1.50:8080 python run.py
SYSWATCH_POLL_INTERVAL_SECONDS=60 SYSWATCH_RETENTION_DAYS=90 python run.py
```

An invalid value is rejected at startup — a non-numeric `SYSWATCH_PORT` or a
`SYSWATCH_RETENTION_DAYS=forever` raises a `ValidationError` rather than
silently falling back to the default.

`SYSWATCH_DATABASE_URL` is read by both the application and Alembic. The value
in `alembic.ini` is deliberately blank and has no effect, so migrations can
never run against a different database than the app.

The agent request timeout is **not** configurable; it is fixed at 5 seconds in
`AgentClient`.

Set `SYSWATCH_POLLING_ENABLED=false` to serve the API without collecting — for
instance when running a second instance alongside one that already polls, since
two pollers writing the same collections just contend for the same rows.

## Database

One table, `snapshots`, holding the agent's nested payload flattened into
columns:

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
  "systemInfo": {"name": "Windows", "version": "11", "hostName": "devbox"}
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
live and historical data.

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

### `GET /snapshots/latest`

The most recently stored snapshot, in the same shape as `GET /snapshot`. Takes
an optional `host` parameter. Returns `404` with `"No snapshot stored yet"` when
nothing matches.

This is the endpoint to fall back to when `GET /snapshot` returns `503` — it
serves the last known state from storage rather than failing.

## Testing

```bash
cd backend
python -m pytest          # whole suite
python -m pytest -v       # per-test names
```

`conftest.py` puts `backend/` on `sys.path`, so pytest must be run from this
directory.

The suite covers the models, `AgentClient`, `SnapshotService`, the API layer,
configuration loading, the database layer (engine, ORM model, migrations,
`SnapshotStore`), the poller, and an end-to-end pass through the real stack with
only the agent's HTTP transport stubbed (`tests/test_snapshot_integration.py`).

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
        api/          # FastAPI routes
        client/       # HTTP client for the C++ agent
        db/           # Engine, session scope, ORM models
        models/       # Pydantic snapshot models
        repositories/ # SnapshotStore, the persistence boundary
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
