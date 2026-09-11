# SysWatch
A cross-platform system monitoring platform consisting of a native C++ agent and a Python backend for collecting, storing, and visualizing system metrics.

# Project overview
SysWatch is a client-server monitoring system. It collects hardware and operating system metrics from multiple machines through a lightweight C++ agent and sends them securely to a centralized Python server. The server stores historical data, provides REST APIs, and offers a web dashboard for monitoring, alerts, and remote management.

# Objectives

- Develop a lightweight, high-performance monitoring agent in modern C++.
- Support Windows, Linux, and macOS.
- Collect system metrics with minimal resource usage.
- Securely transmit metrics to a centralized backend.
- Store historical metrics for long-term analysis.
- Provide REST APIs for data access.
- Visualize metrics through dashboards.
- Build a modular architecture that can be extended with new collectors and services.
- Enable future support for alerting, plugins, and distributed deployments.

# High-Level Architecture

```text
                    +----------------------+
                    |  Client Machines     |
                    | Windows/Linux/macOS  |
                    +----------+-----------+
                               |
                               |
                     Native C++ Monitoring Agent
                               |
                      HTTPS / gRPC / TCP
                               |
                               v
               +-------------------------------+
               |         Python Backend         |
               |-------------------------------|
               | REST API                      |
               | Authentication                |
               | Metric Processing             |
               | Data Validation               |
               +---------------+---------------+
                               |
                 +-------------+-------------+
                 |                           |
                 v                           v
         Time-Series Database         Dashboard / UI
    (InfluxDB, TimescaleDB, etc.)   (Grafana/Web App)
```

# Installing

For a Windows machine, from an elevated prompt:

```text
powershell -ExecutionPolicy Bypass -File deploy\Install-SysWatch.ps1
```

If Python is missing it offers to install it and defaults to no.
`deploy\Install-Prerequisites.ps1` reports what the machine needs without
installing anything, and covers the build tools too.

It installs the agent as a service, sets up the backend and the dashboard,
migrates the database and prompts for the first account. Running it again over
an existing install upgrades in place: it backs up the database first and keeps
the session secret, so nobody is signed out.

[docs/deployment.md](docs/deployment.md) covers upgrades, backups and restores,
reading the service state, managing accounts, and what each startup failure
means.

# Repository Structure

```text
SysWatch/
    agent/                     # Native C++ monitoring agent
        include/
        src/
        tests/
    backend/                   # Python backend (FastAPI)
        alembic/               # Database migrations
        app/
            alerts/            # Rule evaluator and alert engine
            api/               # FastAPI routes
            auth/              # Passwords, sessions, dependencies, admin CLI
            client/            # HTTP client for the C++ agent
            db/                # Engine, session scope, ORM models, backup command
            models/            # Pydantic snapshot, alert and auth models
            repositories/      # Persistence boundary
            services/          # Snapshot service and background poller
        tests/
    dashboard/                 # React + TypeScript web dashboard
        src/
            api/               # Typed HTTP client and mirrored backend models
            auth/              # AuthProvider, useAuth, ProtectedRoute, login route
            components/        # Shared UI: gauges, cards, charts, skeletons, alert indicator
            hooks/             # useApi, usePolling, useUpdateEffect
            layout/            # AppShell — sidebar, header, routed outlet
            lib/               # Formatting, error messages, time ranges, alert helpers
            pages/             # One file per route
    docs/                      # Sprint plans and design notes
    LICENSE
    README.md
    .gitignore
```

# Database Migrations

Schema changes are alembic revisions; an upgrade runs during install and again
on every version bump.

```
alembic upgrade head
```

**Cost.** The upgrade is constant-time, not proportional to stored history.
Measured from the Sprint 5 baseline to head:

| Snapshot rows | Database size | `alembic upgrade head` |
| --- | --- | --- |
| 5,000 | 0.8 MB | 0.05 s |
| 50,000 | 7.2 MB | 0.05 s |
| 200,000 | 28.9 MB | 0.12 s |

The figures are flat because the only table-altering revision adds nullable
columns, which SQLite applies as a metadata change rather than by rewriting the
table. A future revision that adds a NOT NULL column or changes a constraint
would force alembic's batch mode to rebuild the table and copy every row, and
the upgrade would then scale with how long the machine has been monitored —
minutes, with the service down, on a database that has been collecting for a
year. `backend/tests/test_migration_at_scale.py` fails if that happens, so the
change is visible in review rather than during somebody's install.

**Backups.** Take one before upgrading:

```
python -m app.db.backup C:\ProgramData\SysWatch\backups --keep 7
```

`VACUUM INTO`, not a file copy: in WAL mode recent commits live in a `-wal`
sidecar, so copying the database file alone can silently lose them. Each backup
is verified — integrity check and schema revision — before the command reports
success. Backups contain password hashes and session token hashes; keep the
directory out of anywhere world-readable.

# Development Roadmap

## Phase 1 - Native Agent

- [x] Initialize CMake project
- [ ] Cross-platform abstraction layer
- [x] CPU collector
- [x] Memory collector
- [x] Disk collector
- [x] Network collector
- [x] Process collector
- [x] Configuration loader
- [x] JSON serialization
- [ ] Secure communication module

The two left unticked are genuinely absent, not merely unpolished. Every
collector is `#if defined(_WIN32)` with a stub returning zero on the other
branch, which is a placeholder rather than an abstraction layer.

The configuration loader arrived in sprint 12. `config/ConfigFile.cpp` reads
`%PROGRAMDATA%\SysWatch\syswatch.env`, the same restricted file the backend
uses, and it is a file and nothing else: no agent setting comes from an
environment variable, because a machine-wide variable on Windows is readable by
every account on it and one of these settings is a credential.
`CommandLine.cpp` still accepts a mode and nothing else, and there is still no
`--bind` flag or configuration key, because the agent must never listen
anywhere but `127.0.0.1`.

Secure communication is the one that got worse rather than better. It was
unnecessary while the only listener was on loopback; now that the agent pushes
to a backend on another machine it is necessary and still missing, which is
what `allowInsecurePush` exists to admit rather than hide. See
[decisions/0002](docs/decisions/0002-the-agent-speaks-tls-through-winhttp.md)
and [sprint 13](docs/sprint-13.md), which deletes that setting in the sprint
that makes it unnecessary.

---

## Phase 2 - Backend

- [x] FastAPI backend
- [ ] Agent registration
- [x] Metric ingestion API
- [x] Authentication
- [x] Database integration
- [x] Logging
- [x] Configuration management

Agent registration stays unticked because nothing registers *itself*. Sprint 12
built the half that was missing: agents push to an authenticated ingestion
endpoint, each holding a token issued per host with
`python -m app.auth.create_agent_token`, and a snapshot is filed under the host
its credential names rather than the one inside the payload.

What is still absent is enrolment. A token is issued by hand and handed to the
installer - workable for tens of machines, not for hundreds - and an endpoint
that accepted an unknown agent would be the opposite of the identity decision
above. See [decisions/0001](docs/decisions/0001-agents-push-to-the-backend.md)
for the choice and [0003](docs/decisions/0003-what-pushing-cost.md) for what it
cost.

---

## Phase 3 - Storage & Visualization

- [ ] Time-series database
- [x] Historical metric storage
- [x] Dashboard
- [x] Live monitoring
- [x] Historical charts
- [x] Search and filtering

Filtering means host and time window, with paging, through `/snapshots` and the
dashboard's History page. There is no free-text search over metrics and it is
not clear what one would return.

Time-series database stays unticked because SQLite is not one. Bucketed
aggregates are computed per query in `SnapshotStore.series`, which is a
different thing from a store built for the shape, and at one host it is the
right trade.

---

## Phase 4 - Advanced Features

- [x] Alert engine
- [x] Email notifications
- [ ] Plugin system
- [ ] Remote configuration
- [ ] Agent auto-update
- [ ] User management

Notifications are SMTP and webhook, filtered by severity, with acknowledgement
and per-rule silencing. User management is `python -m app.auth.create_admin`
and nothing else: accounts can be created from a command line on the machine,
never through the API, so there is no endpoint that can create an
administrator.

---

## Phase 5 - Production

- [ ] Docker images
- [ ] Kubernetes deployment
- [x] CI/CD pipeline
- [x] Unit tests
- [x] Integration tests
- [ ] Performance optimization
- [x] Security hardening
- [x] Complete documentation

Docker and Kubernetes stay unticked deliberately: this release targets a
Windows install, and containers are a different deployment story that would
want PostgreSQL first.

Performance optimization stays unticked as a roadmap item even though
individual measurements have driven changes - the blocking `/snapshot` route,
WAL mode, the poll interval. None of that was a deliberate pass over the
system, and ticking it would claim one.

---

# Releases

One tag per release, each on the merge that ended its sprint.

| Tag | Commit | Merged |
| --- | --- | --- |
| `v0.1.0` | `1417dd7` | system collector |
| `v0.2.0` | `42bedaf` | agent |
| `v0.3.0` | `24a7152` | HTTP server |
| `v0.4.0` | `3953e2c` | Python backend |
| `v0.5.0` | `8200353` | database integration |
| `v0.6.0` | `ff83b7f` | dashboard |
| `v0.7.0` | `8619103` | process and network monitoring |
| `v0.8.0` | `daba028` | alert engine |
| `v0.9.0` | `6a28b03` | security and authentication |
| `v0.10.0` | `8c0309a` | production hardening |
| `v0.11.0` | `ba4b4c4` | alert delivery |

Sprints 5 to 9 were first tagged `v.0.5.0`, with a stray dot, and re-tagged
without it. `origin` and the GitHub releases have been correct since; a clone
made before the correction was not, and stayed that way, because **`git fetch`
does not move a tag that already exists locally**. `git rev-parse v0.5.0`
answered from the stale copy without a word about it, and five releases
appeared to name one commit.

`git fetch --tags --force` is what updates them. `git ls-remote --tags origin`
is what settles an argument about which is right, because it asks the remote
instead of the copy.

Tagging a release is two claims, and the table checks both: the version
increases, and so does the date.

---