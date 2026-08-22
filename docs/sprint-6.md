# Sprint 6 — Dashboard / UI

**Goal:** give users a visual interface for monitoring the machine.

```text
                    ┌──→ Database
                    │
C++ Agent → Backend ┤
                    │
                    └──→ Dashboard
```

## Starting point

Sprint 5 finished the left half of that diagram. The backend polls the agent
every 10s, writes to SQLite, and serves `/snapshot` (live), `/snapshots`
(history) and `/snapshots/latest` (survives an agent outage). There is no
frontend, and `dashboard/` does not exist.

Three things stand between "the API works" and "a browser can render it", and
none of them are frontend work:

1. **No CORS middleware.** `create_app()` mounts three routers and nothing else.
   Every `fetch` from a dashboard origin is blocked by the browser before the
   backend ever sees it.
2. **Nothing reports agent reachability.** `GET /health` returns a hardcoded
   `{"status": "ok"}` — still true after the agent has been down for an hour.
   The sprint asks for a *Backend/Agent connection status* indicator, and no
   endpoint can currently answer it.
3. **`cpuInfo.usagePercent` is a hardcoded `0.0`.** `CPUCollector::collect()`
   sets it to a literal with a `// placeholder` comment. Sprint 5 flagged this
   and faithfully persisted a column of zeros. A dashboard whose headline tile
   is *CPU usage* cannot ship on top of it — every gauge reads 0%, every chart
   is a flat line. This is why the sprint starts in the agent, not the browser.

A fourth, smaller one: at a 10s poll and 30-day retention the table holds
~259,000 rows, and `/snapshots` is capped at 1000 per page. A 24-hour chart
wants 8,640 points out of that. Charts need server-side bucketing, not paging.

## Locked decisions

| Decision | Final choice | Rationale |
| --- | --- | --- |
| Frontend stack | **React + Vite + TypeScript** | Matches the backend's typed, tested discipline; TS types mirror the Pydantic models. |
| Location | `dashboard/` at repo root | Peer of `agent/` and `backend/`, consistent with the existing structure. |
| Routing | **React Router**, six routes | The six pages are separate views, not tabs over one payload. |
| Charts | **Recharts** | Declarative and React-native; no imperative canvas lifecycle to babysit. |
| Data fetching | **Hand-rolled hooks** | One polling pattern across four endpoints. TanStack Query is a dependency the app has not yet earned. |
| Refresh model | **Polling, 5s default** | The data source is itself a poller; websockets add a protocol for no freshness gain. |
| Live data source | `/snapshots/latest` | Reads storage, so the UI keeps rendering the last known state while the agent is down — exactly when a monitoring UI must not go blank. |
| `/snapshot` in the UI | **Not used** | It fails hard when the agent is down. Its reachability signal moves to `/status`. |
| CORS | Middleware **and** a Vite dev proxy | The proxy alone makes dev work and hides the problem until deployment. |
| Chart history | New `/snapshots/series` | Bucketed aggregates. Paging 8,640 rows into the browser to draw 400 pixels is not a chart API. |
| Multi-host | **Host selector, built but defaulted** | One agent today; `host_name` is already in every query. Cheap now, a rewrite later. |
| CPU placeholder | **Fixed in Phase A** | The sprint's headline metric cannot be a literal. |
| Styling | **CSS Modules** | No runtime, no config, scoped by default. |

## Page → data map

| Page | Reads | Notes |
| --- | --- | --- |
| Overview | `/snapshots/latest`, `/status` | CPU, memory, disk, hostname, OS, last update, connection state |
| CPU | `/snapshots/latest`, `/snapshots/series?metric=cpu` | Gauge, core count, trend |
| Memory | `/snapshots/latest`, `/snapshots/series?metric=memory` | Used/total MB, used % |
| Disk | `/snapshots/latest`, `/snapshots/series?metric=disk` | Used = `totalGB - freeGB`, derived client-side |
| System | `/snapshots/latest`, `/hosts` | OS name/version, hostname, host list |
| History | `/snapshots` | Paged raw table with time-window filters |

---

## Commit plan

### Phase A — Agent: make CPU usage a real number

**1. `feat: sample real CPU usage`**
Replace the `0.0` literal in `CPUCollector.cpp` with a `GetSystemTimes()` delta
between successive calls: `100 * (1 - idleDelta / (kernelDelta + userDelta))`.
*Watch out:* the collector is stateless and `collect()` is `const`. Usage is a
rate, so it needs the previous sample kept on the instance — and the first call
has no delta to work from. Return `0.0` for that one call only, and confirm
`Agent` holds one long-lived collector rather than constructing a fresh one per
cycle, or every reading will be that first call.
*Done when:* `/snapshot` reports a value that moves under load.

**2. `test: cover CPU usage sampling`**
First call returns 0; a second call after a busy loop returns > 0 and <= 100.
*Done when:* the value stays bounded even when the deltas are degenerate.

### Phase B — Backend: make it consumable by a browser

**3. `feat: allow dashboard origins via CORS`**
`CORSMiddleware` in `create_app()`, origins from a new `SYSWATCH_CORS_ORIGINS`
setting (default `http://localhost:5173`).
*Watch out:* a list field behind `env_prefix="SYSWATCH_"` makes pydantic-settings
expect JSON in the environment. Parse a comma-separated string explicitly, or
the first person to set it in a shell gets a validation error at startup.

**4. `feat: report agent connection status`**
`GET /status` → `{"backend": "ok", "agent": "up|down|unknown", "pollerRunning":
bool, "lastCollectedAt": iso|null, "lastPollError": str|null}`.
`agent` is derived: `up` when the last poll succeeded, `down` when it raised,
`unknown` before the first tick or when polling is disabled.
*Requires:* `SnapshotPoller` records nothing about its last tick — `poll_once()`
logs and swallows. Add `last_success_at` / `last_error` set there, and read the
poller off `app.state.poller`, which `lifespan` already assigns.
*Done when:* stopping the agent flips `agent` to `down` within one poll interval.

**5. `feat: add GET /hosts`**
`{"items": [{"hostName": ..., "lastCollectedAt": ..., "snapshotCount": ...}]}`,
backed by a new `SnapshotStore.hosts()` doing a `group by host_name`. Feeds the
host selector and keeps the dashboard from paging the whole table just to
discover which hosts exist.

**6. `feat: add GET /snapshots/series for charts`**
Params `metric` (`cpu|memory|disk`), `host`, `since`, `until`, `bucket`
(`raw|minute|hour|day`). Returns `{"metric": ..., "bucket": ..., "points":
[{"t": iso, "value": float}]}`, averaged per bucket, **oldest first**.
*Note:* that is the opposite of `/snapshots`, which is newest-first for paging.
Say so in the docstring — a silently reversed axis is a nasty bug.
*Watch out:* bucketing on SQLite means `strftime` over `collected_at`. Keep it
inside `SnapshotStore` so the eventual PostgreSQL move stays one file, per
Sprint 5's reasoning.

**7. `test: cover status, hosts and series endpoints`**
Series bucketing and ordering, empty-range behaviour, `/status` in all three
agent states, CORS preflight returning the configured origin.

### Phase C — Dashboard scaffold

**8. `chore: scaffold the dashboard with vite react-ts`**
`dashboard/` via `npm create vite@latest -- --template react-ts`, plus
`react-router-dom`, `recharts`, `vitest`, `@testing-library/react`. Exact
version pins, matching the `requirements.txt` discipline. Vite dev proxy:
`/api` → `http://127.0.0.1:8000`.

**9. `chore: ignore node_modules and dashboard build output`**
`.gitignore` covers Python's `dist/` and `syswatch.db` but has nothing for Node.
Land this before the first `npm install` gets committed by accident.

**10. `feat: add typed API client`**
`src/api/types.ts` mirrors the Pydantic models exactly — `Snapshot`,
`SnapshotPage`, `Series`, `Status`, `HostList` — keeping the backend's camelCase
field names. `src/api/client.ts` wraps `fetch`, throws a typed `ApiError`
carrying the status code, and reads its base URL from `VITE_API_BASE_URL`.
*Done when:* a 404 from `/snapshots/latest` is distinguishable from a network
failure by the caller — the two need different UI.

**11. `feat: add app shell and routing`**
Sidebar nav (Overview, CPU, Memory, Disk, System, History), header with hostname
and a connection dot, `<Outlet/>` content area. All six routes wired with
placeholder bodies, so navigation is reviewable before any page has content.

**12. `feat: add polling and request hooks`**
`useApi(fetcher)` returning `{data, error, loading, refetch}`, and
`usePolling(fetcher, intervalMs)` layered on it.
*Watch out:* three things a naive version gets wrong — abort in-flight requests
on unmount, keep the previous `data` visible while a refresh is in flight (or
every page blanks every 5 seconds), and pause polling when `document.hidden` so
a backgrounded tab stops hammering the API.

### Phase D — Pages

**13. `feat: add shared metric components`**
`StatCard`, `Gauge` (percentage ring), `MetricChart` (Recharts line with shared
axis and tooltip formatting), `TimeRangePicker` (1h / 6h / 24h / 7d). Built once
here rather than five times across the pages that follow.

**14. `feat: add Overview page`**
The sprint's real deliverable: CPU %, memory used/total, disk used/free,
hostname, OS, last update time and connection status on one screen, with no
scrolling on a laptop.
*Last update* renders as relative age ("12s ago"), not a timestamp — a stale
dashboard should be obvious at a glance.

**15. `feat: add CPU page`**
Gauge, core count, and a trend chart from `/snapshots/series?metric=cpu`.

**16. `feat: add Memory page`**
Used vs total MB, used %, trend chart. Format MB into GB above 1024.

**17. `feat: add Disk page`**
Used / free / total GB and a used-% trend. `usedGB` is derived; the agent sends
only `totalGB` and `freeGB`.

**18. `feat: add System page`**
OS name and version, hostname, agent and backend status detail, host list from
`/hosts`.

**19. `feat: add History page`**
Paged table over `/snapshots` with host and time-window filters, using `count`
for pagination and mapping a 422 to an inline "since is after until" message
rather than a generic error.

### Phase E — States, quality, docs

**20. `feat: add loading states`**
Skeletons on first load only. Background refreshes must not flash — a dashboard
that strobes every 5 seconds is unusable.

**21. `feat: add error and empty states`**
Three distinct cases, because they need three different messages: backend
unreachable (network error), no data yet (404 from `/snapshots/latest` — the
normal state on a fresh database), and agent down (`/status` reports `down`, so
show the last known values behind a staleness banner rather than an error page).
*Done when:* killing the agent leaves the dashboard readable, and killing the
backend produces a clear message rather than a blank screen.

**22. `test: cover the dashboard client, hooks and pages`**
Client error mapping, `usePolling` interval and cleanup, and Overview rendering
loading / error / success from mocked responses.

**23. `docs: document the dashboard`**
`dashboard/README.md` (setup, dev server, env vars, build); backend README gains
`/status`, `/hosts`, `/snapshots/series` and `SYSWATCH_CORS_ORIGINS`; root
README adds `dashboard/` to the repository structure and ticks Phase 3
*Dashboard*, *Live monitoring* and *Historical charts*.

---

## Out of scope, flagged

- **Authentication.** The dashboard talks to an unauthenticated API over CORS.
  Fine on `127.0.0.1`; it must not reach a network before Phase 4 auth lands.
  Keeping the default `SYSWATCH_CORS_ORIGINS` at localhost is what stops that
  happening by accident.
- **Alerts and thresholds.** Colouring a gauge red above 90% is tempting, and is
  the thin end of the alert engine. Phase 4.
- **Network collector.** Not implemented in the agent, so there is no network
  page.
- **Serving the built dashboard from FastAPI.** Two dev servers for now; a
  single-origin production build is a Phase 5 deployment concern.
- **Multi-host layout.** The selector exists; a real fleet view — a grid of
  machines, per-host health — waits for agent registration.
