# Sprint 10 — Production Hardening & Deployment

**Goal:** make SysWatch something you install on a Windows machine and leave
running, rather than three processes a developer starts by hand in three
terminals.

```text
                    Windows Service                Windows Service (or console)
              ┌────────────────────────┐        ┌──────────────────────────────┐
              │  SysWatchAgent         │        │  SysWatchBackend             │
              │  127.0.0.1:8080        │◀───────│  uvicorn, one process        │
              │  no auth, loopback     │  poll  │  ┌────────────────────────┐  │
              │  logs to a file        │        │  │ /api/*   the API       │  │
              └────────────────────────┘        │  │ /*       dashboard/dist│  │
                                                │  └────────────────────────┘  │
                                                └──────────────┬───────────────┘
                                                               │  one origin
                                                               ▼
                                                          Browser
```

**The organising decision:** the backend serves the built dashboard from its own
process, so there is one port, one origin, and the cookie/CORS story collapses
to nothing. A reverse proxy in front for TLS stays supported and documented, but
it is no longer required for the app to work.

## Starting point

Sprint 9 left the system secure but still developer-shaped. Thirteen concrete
things stand between that and an install:

1. **`/alerts` is both an API route and a dashboard route.** So is nothing else
   exactly, but `/status`, `/hosts` and `/snapshots` sit in the same namespace
   the SPA routes live in. Serving both from one origin is impossible until the
   API moves under a prefix. That prefix is `/api`, which the dashboard's client
   already assumes — `BASE_URL` defaults to `/api` and only works today because
   the Vite proxy *strips* it again.

2. **19 places construct a `TestClient`.** Prefixing every route breaks all of
   them at once unless the base URL moves with it.

3. **The agent has no logging.** `AgentConfig::logPath` exists and is **never
   read**; the agent writes four `std::cout` lines. A Windows Service has no
   console attached, so as-is it would run completely silently, including its
   failures.

4. **`main()` is a console program.** Signal handler, `stopRequested` flag,
   200 ms poll loop. A service needs `StartServiceCtrlDispatcher`, a
   `ServiceMain`, `SetServiceStatus` transitions and a control handler — while
   the same executable must still run in a console for development.

5. **`SYSWATCH_DATABASE_URL` defaults to `sqlite:///./syswatch.db`** — relative
   to the working directory. A Windows Service starts in `C:\Windows\System32`.
   The default would either fail on permissions or drop a database in a system
   directory, and nobody would find it.

6. **There is no `.env` support.** `SettingsConfigDict` has no `env_file`, so
   Sprint 9's answer for `SYSWATCH_SESSION_SECRET` was "export it". A service
   has no shell to export from.

7. **`run.py` hardcodes `reload=True`.** It is the only entrypoint that reads
   `SYSWATCH_HOST`/`PORT`, and it is unusable in production.

8. **`GET /health` returns a literal.** It answers 200 with a missing database,
   an unapplied migration, or no accounts — which is worse than not having a
   probe, because something will be configured to trust it.

9. **`/docs` and `/openapi.json` are public.** Flagged as open at the end of
   Sprint 9.

10. **CORS defaults are the Vite dev origins.** In the single-origin deployment
    CORS is not needed at all; leaving dev origins configured in production is a
    standing grant to `localhost`.

11. **SQLite runs in WAL mode.** A file copy of `syswatch.db` while the poller
    is writing, without the `-wal` sidecar, produces a backup that restores to a
    stale or torn database.

12. **Three version numbers disagree** — CMake `0.1`, `package.json` `0.0.0`,
    git tags at `v0.6.0`, and nothing in the backend. A package needs one.

13. **There is no `.github/`.** CI is greenfield across three toolchains, and
    the agent's 12 test executables are run by a `for` loop in a README with no
    CTest registration, so nothing reports which one failed.

## Locked decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Deployment shape | **Backend serves `dashboard/dist`; one process, one port** | Removes CORS, removes the cross-origin cookie problem, removes a second thing to install. |
| API location | **Everything under `/api`** | Resolves the `/alerts` collision, and the dashboard client already points there. |
| SPA routing | **Catch-all returning `index.html`; `/api/*` never falls through** | A deep link to `/alerts` must load the app, not 404. |
| Reverse proxy | **Supported and documented, not required** | It is how TLS arrives; it is not how the app becomes usable. |
| Agent as a service | **Same binary, `--service` dispatch; console mode stays the default** | One artefact, and development does not need a service install per rebuild. |
| Service name | `SysWatchAgent` | Matched by the install/uninstall commands. |
| Agent logging | **Rotating file, path from `AgentConfig::logPath`, finally used** | A service with no console must leave evidence somewhere. |
| Backend as a service | **Documented via NSSM/`sc.exe`, not a bespoke wrapper** | Wrapping uvicorn in a Python service host is a lot of machinery to reimplement badly. |
| Production entrypoint | **`serve.py`** beside `run.py`, no reload, reads the same settings | `run.py` stays the development one; neither pretends to be the other. |
| Configuration | **`.env` support added, env vars still win** | A service needs a file to read; an operator needs an override. |
| Data location | **`%PROGRAMDATA%\SysWatch` by default on Windows** | Writable by a service, survives upgrades, is where an admin looks. |
| `/health` vs `/ready` | **`/health` stays a liveness literal; new `/api/ready` checks the database** | Two questions, two answers. Conflating them makes restarts fix nothing. |
| `/docs` | **Off unless `SYSWATCH_DEV_MODE`** | It is a development tool; in production it is a free map of the API. |
| Backups | **`VACUUM INTO`, not a file copy** | Consistent against a live WAL database, which `copy` is not. |
| Version | **One number in `VERSION`, read by all three builds** | A package with three versions in it cannot be supported. |
| CI | **GitHub Actions, `windows-latest`** | The agent is Win32; a Linux runner cannot build or test it. |
| Agent tests | **Registered with CTest** | So CI names the failing test instead of a loop's exit code. |
| Installer | **A PowerShell script, not MSI/WiX** | An MSI is a sprint of its own, and a script is inspectable and fixable on site. |

## The `/api` move

This is the change everything else rests on, so it is worth stating exactly.

```text
before                          after
GET /alerts        (API)        GET /api/alerts        (API)
GET /alerts        (SPA route)  GET /alerts            (dashboard, served index.html)
GET /health                     GET /api/health
GET /              → JSON       GET /                  (dashboard)
```

The Vite dev proxy currently rewrites `/api/x` → `/x`. That rewrite is
**deleted**: with the prefix real on both sides, development and production
address the API identically, which is the point.

`TestClient(app, base_url="https://testserver/api")` keeps every existing
relative path in the tests working unchanged.

## Configuration after this sprint

| Variable | Default | Notes |
| --- | --- | --- |
| `SYSWATCH_DATA_DIR` | `%PROGRAMDATA%\SysWatch` | New. Base for the database and logs |
| `SYSWATCH_DATABASE_URL` | `sqlite:///<data dir>/syswatch.db` | Derived, no longer CWD-relative |
| `SYSWATCH_LOG_DIR` | `<data dir>\logs` | New |
| `SYSWATCH_LOG_LEVEL` | `INFO` | New |
| `SYSWATCH_DASHBOARD_DIR` | `<install dir>\dashboard` | New. Unset disables static serving |
| `SYSWATCH_SESSION_SECRET` | *(none)* | Unchanged; still fatal when missing |
| `SYSWATCH_DEV_MODE` | `false` | Now also gates `/docs` |
| `SYSWATCH_CORS_ORIGINS` | **empty** | Changed. Single-origin needs none; dev sets it |

Read from the environment first, then `SYSWATCH_CONFIG_FILE` (default
`<data dir>\syswatch.env`), then the defaults.

---

## Commit plan

### Phase A — One origin

**1. `feat: move the API under an /api prefix`**
`include_router(..., prefix="/api")` for every router including health. Drop the
JSON `GET /`. `conftest.py` and the 8 module-level clients take
`base_url=".../api"`, so no test path changes.
*Watch out:* `test_cors.py` preflights `/health` by absolute path, and
`test_authorization.py` lists routes explicitly — both need the prefix.
*Done when:* the full suite passes with no path edited inside a test body.

**2. `feat: remove the dev proxy rewrite`**
`vite.config.ts` keeps the proxy, loses `rewrite`. The dashboard now talks to
`/api/...` in both environments.
*Done when:* `npm run dev` against the backend still logs in.

**3. `feat: serve the built dashboard from the backend`**
Mount `SYSWATCH_DASHBOARD_DIR` as static files with an SPA fallback: anything
not under `/api` and not an existing file returns `index.html`.
*Watch out:* the fallback must not swallow `/api/*` — an API 404 has to stay a
JSON 404, or every client bug looks like the dashboard loading.
*Watch out:* unset the setting and the backend must behave exactly as before,
so the API is still usable without a built dashboard.
*Done when:* `npm run build`, start the backend, open `http://127.0.0.1:8000/alerts`
in a browser, and it deep-links into the app and logs in.

### Phase B — Configuration and paths

**4. `feat: read configuration from a file`**
`env_file` on `SettingsConfigDict`, path from `SYSWATCH_CONFIG_FILE`.
Environment still wins over the file.
*Watch out:* `.gitignore` already covers `.env*`; the example file committed
must be `syswatch.env.example` with no real secret in it.

**5. `feat: derive data paths from a data directory`**
`SYSWATCH_DATA_DIR`, defaulting to `%PROGRAMDATA%\SysWatch` on Windows and
`./data` elsewhere. `database_url` and `log_dir` derive from it. Create the
directory at startup.
*Watch out:* this changes where an existing installation's database is looked
for. Log loudly when the configured path does not exist and the old
`./syswatch.db` does.
*Done when:* starting from `C:\Windows\System32` puts the database in
ProgramData.

**6. `feat: add a production entrypoint`**
`serve.py`: no reload, host/port from settings, `--workers` refused with an
explanation (SQLite plus an in-process rate limiter plus one poller do not
survive multiple workers).
*Done when:* `python serve.py` runs the app with no development behaviour.

**7. `feat: drop development defaults`**
`SYSWATCH_CORS_ORIGINS` defaults to empty. `/docs`, `/redoc` and
`/openapi.json` are served only under `SYSWATCH_DEV_MODE`.
*Watch out:* `create_app()` must pass `docs_url=None` rather than trying to
remove routes afterwards.

### Phase C — Health and logging

**8. `feat: add a readiness check`**
`GET /api/ready`: `200` when the database opens, the schema is at head and at
least one account exists; `503` with a reason otherwise. `/api/health` stays
the liveness literal.
*Watch out:* this must not require a session — a supervisor has none — but it
must also not leak more than a reason string.
*Done when:* deleting the database file turns `/api/ready` red and leaves
`/api/health` green.

**9. `feat: log to files with rotation`**
`RotatingFileHandler` into `SYSWATCH_LOG_DIR`, level from settings, console
handler kept when a console exists. Startup logs version, data dir, auth state
and agent URL; shutdown logs the reason.
*Watch out:* nothing may log a password, a token or a token hash — the rule
`app/auth/` already follows, now enforced by a test that greps the log after a
login.

**10. `feat: record poller failures worth acting on`**
The poller already stores `last_error`; make consecutive failures log once at
`WARNING` with a count rather than every tick, and log recovery. Add the agent's
URL to the message so two instances are distinguishable.

### Phase D — The agent as a Windows Service

**11. `feat(agent): extract the agent runtime from main`**
A `runUntilStopped(config, shouldStop)` seam so console mode and service mode
share one lifecycle. No behaviour change.
*Done when:* the existing 12 test executables still pass.

**12. `feat(agent): add file logging`**
A small `Logger` writing to `AgentConfig::logPath`, finally used: startup,
bind address and port, collection failures, shutdown. Size-based rotation.
*Watch out:* the log directory may not exist and may not be writable; failing
to open the log must not stop the agent from collecting.

**13. `feat(agent): run as a Windows Service`**
`--service` enters `StartServiceCtrlDispatcher`; anything else runs the console
path. `ServiceMain` reports `START_PENDING` → `RUNNING`, the control handler
answers `STOP` and `SHUTDOWN` by setting the stop flag.
*Watch out:* the SCM kills a service that does not report `RUNNING` inside its
timeout; report it before starting the collector, not after.

**14. `feat(agent): add install and uninstall commands`**
`agent.exe --install` / `--uninstall`: `CreateService` with
`SERVICE_AUTO_START`, a description, and recovery actions (restart after
5s/10s/60s, reset daily). Refuse without administrator rights, with a clear
message rather than an error code.
*Done when:* install, reboot, and `/snapshot` answers without anyone logging in.

**15. `test(agent): cover the service seam`**
The stop flag ends `runUntilStopped`; the logger survives an unwritable path;
argument parsing routes `--service`, `--install`, `--uninstall` and bare
invocation correctly. Registered with CTest alongside the existing executables.

### Phase E — Security close-out

**16. `feat: refuse an unsafe production configuration`**
Extend `verify_security_configuration`: `SYSWATCH_AUTH_ENABLED=false` becomes
**fatal** unless `dev_mode`, rather than a warning. Refuse a `cors_origins`
entry that is not `https://` when not in dev mode.
*Watch out:* the test suite runs with auth disabled by design — it must set
`dev_mode` too, or 500 tests stop at startup.

**17. `chore: audit the repository for committed secrets`**
Grep history for key-shaped strings, confirm `.gitignore` covers `*.env`,
`.env*`, `syswatch.db*` and the log directory, and record the result. Add the
example config with placeholder values only.

### Phase F — Database reliability

**18. `feat: add a backup command`**
`python -m app.db.backup <dest>` using `VACUUM INTO`, which is consistent
against a live WAL database in a way `copy` is not. Timestamped filenames,
optional retention count.
*Done when:* a backup taken while the poller is writing restores and opens at
the same schema revision.

**19. `test: upgrade a realistic database`**
Build a database at the Sprint 5 baseline with thousands of snapshot rows,
alert history and users, then `upgrade head` and assert row counts, indexes and
the alembic version. Time it, and record the number in the README so a slow
migration is a known quantity rather than a surprise during an install.

### Phase G — Packaging

**20. `chore: single source of version`**
A `VERSION` file at the repo root. CMake reads it into `project(... VERSION)`,
`package.json` is synced by a script, the backend exposes it at `/api/health`
and logs it at startup.

**21. `feat: add a deployment script`**
`deploy/Install-SysWatch.ps1`: check prerequisites, copy the agent, backend and
`dashboard/dist` into an install directory, create the data directory, generate
a session secret if absent, run `alembic upgrade head`, prompt for the first
admin, install both services, start them, and print the URL.
`Uninstall-SysWatch.ps1` stops and removes the services and leaves the data
directory alone unless `-RemoveData`.
*Watch out:* the upgrade path must not regenerate the session secret — that
would log everyone out on every deploy.
*Done when:* a clean install on a fresh machine reaches a working login, and
running the installer again over it upgrades without data loss.

### Phase H — CI

**22. `ci: build and test the agent`**
`windows-latest`, MinGW toolchain, `cmake --build`, `ctest --output-on-failure`.

**23. `ci: test the backend and dashboard`**
Python matrix on the pinned version, `pytest`; Node 20, `npm ci`, `tsc -b`,
`oxlint`, `vitest run`, `npm run build`. Cached where it is safe to cache.

**24. `ci: publish artifacts and releases`**
Upload the agent binary, backend source and dashboard build on every run; on a
`v*` tag, attach them to a GitHub Release.
*Done when:* the branch protection rule requires agent, backend and dashboard
checks, and a red check blocks the merge.

### Docs

**25. `docs: document deployment and operations`**
A new `docs/deployment.md`: install, upgrade, uninstall, backup and restore,
where the data and logs live, how to reset a password, how to read the service
state, and what each failure at startup means. Backend README gains the `/api`
prefix, the new settings and `/api/ready`. Dashboard README loses the proxy
rewrite and gains the served-from-backend model. Agent README gains the service
commands. Root README ticks Phase 5.

*Combinable:* 1+2 (the prefix and the proxy are one change seen from two
sides), 11+12, 22+23. Lands around 20–25 commits.

---

## Out of scope, flagged

- **MSI/WiX installer.** The PowerShell script is the deliverable; a real
  installer with upgrade codes and rollback is its own sprint.
- **TLS termination and certificates.** Documented as a reverse-proxy
  responsibility, not automated here.
- **PostgreSQL.** The migration path gets written down; nothing runs against it.
  `SnapshotStore` and friends are what keep it a configuration change.
- **Multi-host / agent registration.** One agent, one backend, one machine. A
  fleet needs agent identity and credentials, which is Phase 2 work that never
  happened.
- **Docker and Kubernetes.** This sprint targets a Windows install. Containers
  are a different deployment story and would want PostgreSQL first.
- **Metrics export (Prometheus etc.).** "Operational metrics where useful" here
  means log lines and `/api/ready`, not a scrape endpoint.
- **Auto-update.** The installer can upgrade; the agent does not update itself.
- **Linux/macOS service integration.** The collectors are already Win32-only;
  systemd units follow the platform layer, not this sprint.
