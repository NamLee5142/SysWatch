# SysWatch Dashboard

React + TypeScript single-page app that renders live and historical system
metrics from the [backend](../backend/README.md) API.

```text
Browser  ->  Vite dev server (this app)  ->  Python backend
             :5173                          :8000
```

Every page polls the backend directly — there is no shared request cache and
no state management library. A page that needs the latest snapshot fetches it
itself, on its own 5-second interval, independent of every other page. See
"Data fetching" below for why.

## Requirements

- Node.js 20 or newer
- The [backend](../backend/README.md) running and reachable — the dashboard
  renders nothing useful on its own

## Setup

```bash
cd dashboard
npm install
```

## Running

```bash
npm run dev
```

Starts the Vite dev server at `http://localhost:5173`. Requests to `/api/*`
are proxied to `http://127.0.0.1:8000` (see `vite.config.ts`), so the app and
backend appear same-origin to the browser and the backend's CORS grant is
never exercised in development.

Start the backend first, or the earliest requests will fail with the network
error message rather than data — see `dashboard/src/lib/errors.ts` for how
that failure is told apart from "no data yet" and "backend rejected the
request".

## Building

```bash
npm run build
```

Runs `tsc -b` then `vite build`, emitting a static bundle to `dist/`. A
production build has no dev-server proxy, so requests go straight to
`VITE_API_BASE_URL`; without it they fall back to `/api`, which only resolves
if this bundle happens to be served from the same origin as the backend.
There is no such deployment yet — see "Serving the built dashboard from
FastAPI" in `docs/sprint-6.md`'s out-of-scope list.

```bash
npm run preview   # serve the dist/ build locally, for a final check
```

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `/api` | Base URL the API client builds every request against |

Set it in a `.env.local` file (gitignored) or inline:

```bash
VITE_API_BASE_URL=http://192.168.1.50:8000 npm run dev
```

Only relevant when the backend is not reachable at the dev proxy's target, or
in a production build that is not served from the backend's own origin. Vite
only exposes variables prefixed `VITE_` to client code — see
[`src/vite-env.d.ts`](src/vite-env.d.ts).

## Testing and linting

```bash
npm run test         # vitest, once
npm run test:watch   # vitest, watch mode
npm run lint         # oxlint
```

Component tests run under `jsdom` (`vite.config.ts`'s `test.environment`),
with `src/test/setup.ts` wiring in `@testing-library/jest-dom`'s matchers.
Every hook and page that fetches is tested against a mocked `api/client`
module, not a real backend — `getLatestSnapshot`/`getStatus`/etc. are
`vi.fn()`s the tests script directly, which is what lets loading, error and
stale-tab-polling states be tested deterministically rather than racing a
real server.

## Data fetching

Two hooks, layered:

- **`useApi(fetcher)`** — fetches once on mount, exposes `{ data, error,
  loading, refetch }`. Never blanks `data` back to `undefined` on a refetch;
  a page checking `loading && !data` shows a spinner only on the very first
  load, and keeps last-known-good data on screen through every refresh after
  that.
- **`usePolling(fetcher, intervalMs)`** — `useApi` plus an interval, paused
  while the tab is hidden (`document.hidden`) and refetched once immediately
  when the tab becomes visible again, rather than waiting out the rest of a
  stale interval.

There is deliberately no shared cache layer (no React Query, no SWR, no
context provider re-broadcasting one fetch to every consumer): `AppShell`
polls `/snapshots/latest` and `/status` for its header, and every page below
it polls at least one of the same endpoints again independently for its own
content. That is duplicated traffic against a cheap SQLite read on a 5-second
interval — judged not worth the complexity of a shared cache for this sprint.
Revisit if the backend ever needs to shed that load.

`useUpdateEffect` is the third hook, unrelated to fetching state itself: it
runs an effect on every dependency change **except** the first render, for
refetching when a `TimeRangePicker` selection or `HistoryPage` filter changes
without double-fetching alongside `useApi`'s own mount-time fetch.

## Pages

| Route | Renders |
| --- | --- |
| `/` | Overview — one tile per metric plus connection state |
| `/cpu`, `/memory`, `/disk` | A gauge plus a trend chart, independently loaded |
| `/system` | Host identity, agent/poller connection detail, and the host list from `GET /hosts` |
| `/history` | Filterable, paged table over `GET /snapshots` |

`AppShell` wraps every route with the sidebar and header, including a
staleness banner (`StalenessBanner`) shown above the page content whenever
`GET /status` reports the agent down — the numbers on screen stay real (they
are storage-backed), just possibly out of date, and the banner says so rather
than leaving that to the small header dot alone.

## Structure

```text
dashboard/
    src/
        api/            # Typed HTTP client and mirrored backend models
        components/     # Shared UI: gauges, cards, charts, skeletons
        hooks/          # useApi, usePolling, useUpdateEffect
        layout/         # AppShell — sidebar, header, routed outlet
        lib/            # Formatting, error messages, time ranges, constants
        pages/          # One file per route
        App.tsx         # BrowserRouter, for real navigation
        routes.tsx      # AppRoutes — kept apart from App so tests can drive
                         # it inside a MemoryRouter instead of window.history
    vite.config.ts      # Dev proxy, vitest config
```
