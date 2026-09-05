# SysWatch Dashboard

React + TypeScript single-page app that renders live and historical system
metrics from the [backend](../backend/README.md) API.

```text
development   Browser  ->  Vite dev server  ->  Python backend
                           :5173                :8000

production    Browser  ->  Python backend, serving this app's dist/
                           :8000
```

In production the backend serves the built dashboard itself, so there is one
process, one port and one origin. That removes CORS, removes the cross-origin
cookie problem, and removes a second thing to install. In development the Vite
proxy produces the same single-origin shape, so the two environments do not
differ in the ways that usually bite.

Every page polls the backend directly — there is no shared request cache and
no state management library. A page that needs the latest snapshot fetches it
itself, on its own 5-second interval, independent of every other page. See
"Data fetching" below for why.

## Requirements

- Node.js 22 or newer (CI builds on 22; Vite 8 wants 20.19+ or 22.12+)
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

There is deliberately **no path rewrite** in that proxy. The backend serves its
API under `/api` as well, so a request path that works in development works
unchanged in production - and the client has one base URL rather than one per
environment.

Start the backend first, or the earliest requests will fail with the network
error message rather than data — see `dashboard/src/lib/errors.ts` for how
that failure is told apart from "no data yet" and "backend rejected the
request".

You will also need an account to sign in with, and the backend needs a session
secret to start at all — see the backend's
[Setup](../backend/README.md#setup). In development it is usually run with
`SYSWATCH_DEV_MODE=true`, which drops the session cookie's `Secure` flag so it
survives plain HTTP.

## Building

```bash
npm run build
```

Runs `tsc -b` then `vite build`, emitting a static bundle to `dist/`.

A production build has no dev-server proxy, so requests go to
`VITE_API_BASE_URL`; without it they fall back to `/api`, which resolves
because the backend serves this bundle from its own origin. Point
`SYSWATCH_DASHBOARD_DIR` at `dist/` and the backend serves it, answering any
route it does not recognise with `index.html` so a deep link to `/alerts`
loads the app instead of a 404. `/api/*` never falls through to that catch-all:
an unknown API path answers `404` as JSON, so a client bug does not arrive
disguised as HTML.

[docs/deployment.md](../docs/deployment.md) covers installing that arrangement;
the installer does it for you.

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
in a production build served from somewhere other than the backend's own
origin - which then also needs `SYSWATCH_CORS_ORIGINS` set on the backend, and
an `https://` origin, because the session cookie is `Secure`. Vite
only exposes variables prefixed `VITE_` to client code — see
[`src/vite-env.d.ts`](src/vite-env.d.ts).

## Testing and linting

```bash
npm run test         # vitest, once
npm run test:watch   # vitest, watch mode
npm run lint         # oxlint
```

`renderWithAuth` (in `src/test/`) supplies a known identity directly rather
than mounting `AuthProvider`, so a page test can say "as a viewer" without
stubbing `/auth/me`. `src/App.session.test.tsx` is the exception: it stubs only
`fetch`, so the real client, provider and routes all run — the one place the
wiring between them is proved rather than assumed.

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

## Authentication

Everything except `/login` sits behind a session.

```text
App
 └─ AuthProvider          one GET /auth/me on mount
     └─ AppRoutes
         ├─ /login        LoginRoute → LoginPage
         └─ ProtectedRoute
             └─ AppShell  every other page
```

**The cookie is never touched by this code.** It is `HttpOnly`, so page
JavaScript cannot read it; the browser attaches it and `credentials: 'include'`
in the API client is all that is needed to carry it. There is no token in
`localStorage` and nothing to keep in React — the only session state here is
*who* the backend says you are.

- **`AuthProvider`** asks `/auth/me` once on mount. While that is in flight it
  renders a blank screen rather than the login page: a refresh with a perfectly
  good session would otherwise flash a login form and replace it, which reads as
  having been logged out. Any failure, including the backend being unreachable,
  settles as anonymous — the login page then reports the real reason.
- **`useAuth()`** exposes `status`, `user`, `isAdmin`, `signIn`, `signOut`. It
  throws outside a provider, so a mis-wired component fails loudly instead of
  silently behaving as though nobody were logged in.
- **`ProtectedRoute`** redirects an anonymous visitor to `/login`, remembering
  where they were headed so signing in resumes it rather than dumping everyone
  on Overview.
- **A 401 from anywhere** ends the session. Any of the five polls a page runs
  can be the one that finds out, so they all report through the client's
  `setUnauthorizedHandler` rather than each deciding what to do; `AuthProvider`
  registers the handler that drops the user and lets `ProtectedRoute` take over.
  The login call and the first-load `/auth/me` are exempt — a wrong password is
  not an ended session, and neither is never having logged in.

### Roles in the UI

A viewer sees every page. What they do not see is the **Add rule** button and
the per-row Enable/Disable and Delete controls on the Alerts page.

**Hiding those is a courtesy, not a control.** `require_admin` on the backend
refuses the calls however they are made — through the console, curl, or a
dashboard built from a modified bundle. If a request does get through the UI, a
`403` is reported as "Only an admin can change alert rules" rather than a
generic failure.

## Pages

| Route | Renders |
| --- | --- |
| `/` | Overview — one tile per metric (CPU, memory, disk, processes, network) plus connection state |
| `/cpu`, `/memory`, `/disk` | A gauge plus a trend chart, independently loaded |
| `/processes` | Process count, a top-by-memory table, and a count trend chart (`metric=processes`) |
| `/network` | One card per interface with its send/receive rates, plus received and sent throughput charts (`metric=net_recv` / `net_sent`) |
| `/system` | Host identity, agent/poller connection detail, and the host list from `GET /hosts` |
| `/history` | Filterable, paged table over `GET /snapshots` |
| `/login` | The only route outside the shell — see [Authentication](#authentication) |
| `/alerts` | Active alerts, recently resolved alerts, and a read-only list of the configured rules |

The process and network pages fall back to a "this agent does not report …
data" message when the latest snapshot has no such block (an agent built
before Sprint 7). `MetricChart` reads the series' `unit` to pick its axis —
a fixed 0-100 scale for percentages, an auto scale with `formatBytesPerSec`
ticks for throughput, whole numbers for a count.

The Alerts page polls `GET /alerts/active`, `GET /alerts?state=ok` and
`GET /alert-rules` independently. Value and threshold are shown in each
metric's own unit (`src/lib/alerts.ts` mirrors the backend's metric → unit
map, since the alert payload carries the metric but not the unit). Rule
editing is API-only for now — the page only lists rules.

`AppShell` wraps every route with the sidebar and header, including the signed-in
account and a Sign out button. The role is shown beside the username because it
explains why the alert-rule controls are or are not there. The header carries a
🔔 indicator that polls `GET /alerts/active` and links to `/alerts`; it is
shown even at zero (dimmed) so "nothing is firing" is visible rather than
absent, and turns red with the count when something is. The header also shows
a staleness banner (`StalenessBanner`) above the page content whenever
`GET /status` reports the agent down — the numbers on screen stay real (they
are storage-backed), just possibly out of date, and the banner says so rather
than leaving that to the small header dot alone.

## Structure

```text
dashboard/
    src/
        api/            # Typed HTTP client and mirrored backend models
        auth/           # AuthProvider, useAuth, ProtectedRoute, LoginRoute
        components/     # Shared UI: gauges, cards, charts, skeletons, the alert indicator
        hooks/          # useApi, usePolling, useUpdateEffect
        layout/         # AppShell — sidebar, header, routed outlet
        lib/            # Formatting, error messages, time ranges, constants, alert helpers
        pages/          # One file per route
        test/           # renderWithAuth and other shared test helpers
        App.tsx         # BrowserRouter, for real navigation
        routes.tsx      # AppRoutes — kept apart from App so tests can drive
                         # it inside a MemoryRouter instead of window.history
    vite.config.ts      # Dev proxy, vitest config
```
