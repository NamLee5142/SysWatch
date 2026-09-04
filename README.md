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

- [ ] Initialize CMake project
- [ ] Cross-platform abstraction layer
- [ ] CPU collector
- [ ] Memory collector
- [ ] Disk collector
- [x] Network collector
- [x] Process collector
- [ ] Configuration loader
- [ ] JSON serialization
- [ ] Secure communication module

---

## Phase 2 - Backend

- [x] FastAPI backend
- [ ] Agent registration
- [x] Metric ingestion API
- [x] Authentication
- [x] Database integration
- [x] Logging
- [x] Configuration management

---

## Phase 3 - Storage & Visualization

- [ ] Time-series database
- [ ] Historical metric storage
- [x] Dashboard
- [x] Live monitoring
- [x] Historical charts
- [ ] Search and filtering

---

## Phase 4 - Advanced Features

- [x] Alert engine
- [ ] Email notifications
- [ ] Plugin system
- [ ] Remote configuration
- [ ] Agent auto-update
- [ ] User management

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

---