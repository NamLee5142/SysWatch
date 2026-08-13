# SysWatch Backend

FastAPI service that fetches system snapshots from the C++ agent over HTTP and
serves them as validated, typed JSON.

```text
HTTP client  ->  Python backend (this service)  ->  C++ agent
                 :8000                              :8080
```

## Requirements

- Python 3.10 or newer (verified on 3.14.2)
- A running SysWatch C++ agent for `/snapshot` to return data

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux / macOS
pip install -r requirements.txt
```

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

```bash
SYSWATCH_AGENT_BASE_URL=http://192.168.1.50:8080 python run.py
```

An invalid value is rejected at startup — a non-numeric `SYSWATCH_PORT` raises
a `ValidationError` rather than silently falling back to the default.

The agent request timeout is **not** configurable; it is fixed at 5 seconds in
`AgentClient`.

## API

Interactive documentation is served at `/docs`, with the raw schema at
`/openapi.json`.

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

## Testing

```bash
cd backend
python -m pytest          # whole suite
python -m pytest -v       # per-test names
```

`conftest.py` puts `backend/` on `sys.path`, so pytest must be run from this
directory.

The suite covers the models, `AgentClient`, `SnapshotService`, the API layer,
configuration loading, and an end-to-end pass through the real stack with only
the agent's HTTP transport stubbed (`tests/test_snapshot_integration.py`).

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
    app/
        api/          # FastAPI routes
        client/       # HTTP client for the C++ agent
        models/       # Pydantic snapshot models
        services/     # Service layer between API and client
    tests/
    config.py         # Settings, read from SYSWATCH_ env vars
    conftest.py       # Puts backend/ on sys.path for pytest
    run.py            # Development entrypoint
```
