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
            db/                # Engine, session scope, ORM models
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
- [ ] CI/CD pipeline
- [ ] Unit tests
- [ ] Integration tests
- [ ] Performance optimization
- [ ] Security hardening
- [ ] Complete documentation

---