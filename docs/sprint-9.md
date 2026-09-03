# Sprint 9 — Security & Authentication

**Goal:** put authentication and role-based authorization at the FastAPI
boundary, move every operational endpoint behind it, switch CORS to a
credentialed model, add a login flow and permission-aware UI to the dashboard,
and lock the C++ agent to loopback so none of this can be bypassed.

```text
┌─ React Dashboard ──────────┐
│  /login → AuthContext      │
│  ProtectedRoute wraps all  │
│  admin-only rule controls  │
└──────────┬─────────────────┘
           │  fetch(..., credentials: 'include')   HttpOnly session cookie
           ▼
┌─ FastAPI Backend ──────────────────────────────┐
│  /health              public                   │
│  /auth/login /logout /me                       │
│  security headers · login rate limit · CORS    │
│  require_authenticated_user  →  /status /snapshot(s) /hosts /alerts │
│  require_admin               →  POST/PUT/DELETE /alert-rules        │
└──────────┬─────────────────────────────────────┘
           │  127.0.0.1 only, no auth (internal)
           ▼
┌─ SysWatch Agent (C++) ─────┐
│  binds 127.0.0.1:8080      │
│  no user, no port exposed  │
└────────────────────────────┘
```

**The principle:** authentication belongs at the backend boundary. The agent
stays an internal monitoring component — it does **not** learn about users, and
the dashboard never talks to it directly.

## Starting point

The stack works end to end for an anonymous user. Everything below assumes that,
and nine facts narrow at the point where a session cookie is introduced.

1. **~300 backend tests and ~260 dashboard tests assume no auth.** Nearly every
   one calls a now-protected endpoint or renders a page that polls one. Turning
   auth on breaks them all in one commit unless the test harness gains a way to
   present an authenticated caller first.

2. **Every backend API test builds its own `TestClient` at module scope.**
   Nine files do `app = create_app(); client = TestClient(app)` at import, each
   with its own in-memory DB fixture. `conftest.py` is four lines of `sys.path`.
   There is no shared `client` / `admin_client` / `viewer_client` to inject, and
   `app.dependency_overrides` on a per-file app instance cannot be reached from
   `conftest`.

3. **CORS is `allow_credentials=False` with `allow_headers=["*"]`.** A cookie
   needs `allow_credentials=True`, and the CORS spec forbids `*` for origin
   **or** headers once credentials are allowed — Starlette will need explicit
   method and header lists, and `allow_origins` must already be the configured
   list (it is) with no `"*"` fallback ever.

4. **The dashboard has no auth surface at all.** `api/client.ts` calls `fetch`
   with no `credentials`, there is no context provider, no `/login` route, and
   `App.tsx` is a bare `<BrowserRouter>`. A `401` from any of the ~5 polling
   hooks a page mounts has nowhere to go — it currently lands in each hook's
   `error` state as a generic failure.

5. **`get_settings()` is uncached and there is no `.env` support.** A required
   `SYSWATCH_SESSION_SECRET` must fail **at startup**, loudly, once — not on the
   first request, and not silently fall back to a shipped default.

6. **`AppShell` polls `/status`, `/snapshots/latest` and `/alerts/active` on
   every route.** All three move behind auth, so the shell may only mount once a
   session exists, and `/login` must poll nothing — today every page is a child
   of `AppShell` and inherits its polling.

7. **Sprint 8 left alert-rule editing API-only.** The dashboard's rules list is
   read-only for everyone. Phase I is not just "gate an existing control" — it
   needs an admin create/edit/delete UI that does not exist yet.

8. **The agent already binds `127.0.0.1`** (`HTTPServer.cpp`, `inet_pton(...,
   "127.0.0.1", ...)`), but nothing tests that or says why it matters. The
   entire auth model rests on the agent being unreachable from anywhere but the
   backend process's own host.

9. **Dev is plain HTTP through the Vite proxy.** The browser sees one origin
   (`localhost:5173`); requests are rewritten to `127.0.0.1:8000`. A `Secure`
   cookie is allowed on `localhost` over HTTP by modern browsers, but `SameSite`
   still needs a choice, and the backend must **not** set a `Domain` attribute
   or the proxy's implicit host-scoping breaks.

New dependency: **`argon2-cffi`** (pinned), nothing else. No `passlib`, no
`python-jose`, no rate-limit library.

## Locked decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Auth factor | Username + password | Single-user/local deployment; MFA is out of scope |
| Credential transport | Server-side session, **HttpOnly** cookie | No token in `localStorage`, nothing for page JS to read or leak |
| Password hash | **Argon2id** via `argon2-cffi` directly | Modern default; skips `passlib`'s bcrypt-version detection breakage |
| Session token | Opaque 256-bit random; store **`HMAC-SHA256(secret, token)`** | A DB read cannot forge or replay a session; the secret gives itself a real job |
| Session store | SQLite `sessions` table | No new infrastructure; same engine as everything else |
| Session expiry | **Absolute**, `expires_at = login + TTL` | `last_seen_at` is recorded but does not extend the window — simpler, tighter |
| Roles | `admin`, `viewer` | Two is enough for the one authz split this sprint needs |
| First admin | **CLI** `python -m app.auth.create_admin` (getpass) | No `POST /setup-admin` to forget to disable; password never in shell history |
| Enforcement | Per-router `Depends(require_authenticated_user)`; `Depends(require_admin)` on the three write routes | No middleware; the dependency tree is the policy |
| `SESSION_SECRET` | No default. Startup **fails** when `auth_enabled` and not `dev_mode` and it is unset | Plan requirement: production cannot boot insecure |
| `dev_mode` | `SYSWATCH_DEV_MODE` (default false) → cookie `Secure` off, a fixed dev secret allowed, relaxed CSP note | One explicit flag instead of scattered "is this dev?" checks |
| CORS | `allow_credentials=True`, explicit `allow_methods` / `allow_headers`, origins from config, never `"*"` | Required once cookies are in play |
| Test strategy | `conftest.py` gains a shared `app` + `client` / `admin_client` / `viewer_client` / `anon_client`; API test files migrate off module-level `TestClient` | Secure-by-default in tests too; the migration is mechanical and unavoidable once every route has a dependency |
| Auth default | `SYSWATCH_AUTH_ENABLED` defaults **true** | The insecure state should be the one you opt into |
| Login abuse | In-process fixed-window counter on `POST /auth/login`, `429` past the limit | Localhost, single worker — a distributed limiter is not this sprint |
| API CSP | `default-src 'none'; frame-ancestors 'none'` on API responses | It serves JSON; the dashboard's CSP is a separate, deployment-time concern |
| Agent | Stays loopback-only, **no auth, no configurable bind host** | It is internal; a bind-host option would just be a footgun |
| Generic auth failure | Same `401` body for unknown user and wrong password; verify a dummy hash when the user is missing | No username-enumeration oracle, no timing oracle |

## Schema

Two tables. One Alembic revision, `down_revision = 0a33e83916fa`, batch mode,
named through the existing convention.

### `users`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `username` | text, not null, **unique** | Case-sensitive; the login key |
| `password_hash` | text, not null | Argon2id encoded hash — never returned by any endpoint |
| `role` | text, not null | `admin` or `viewer` |
| `enabled` | boolean, not null, default true | A disabled user's sessions stop working on their next request |
| `created_at` / `updated_at` | datetime (UTC) | Stamped by the service, naive UTC, like every other table |

### `sessions`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `token_hash` | text, not null, **unique** | `HMAC-SHA256(SESSION_SECRET, raw_token)`. The raw token lives only in the cookie |
| `user_id` | integer FK → `users.id`, `ON DELETE CASCADE` | Deleting a user ends their sessions |
| `expires_at` | datetime (UTC) | Absolute; checked on every authenticated request |
| `created_at` | datetime (UTC) | |
| `last_seen_at` | datetime (UTC) | Updated per request, for visibility only |

Expired rows are swept opportunistically: `SessionService.prune_expired()` runs
from the poller's existing hourly housekeeping pass (next to snapshot
retention), and a login also clears the caller's own stale rows.

## Authorization

| Endpoint | Anonymous | Viewer | Admin |
| --- | --- | --- | --- |
| `GET /health` | ✅ | ✅ | ✅ |
| `POST /auth/login`, `/auth/logout` | ✅ | ✅ | ✅ |
| `GET /auth/me` | `401` | ✅ | ✅ |
| `GET /status` | `401` | ✅ | ✅ |
| `GET /snapshot`, `/snapshots`, `/snapshots/latest`, `/snapshots/series` | `401` | ✅ | ✅ |
| `GET /hosts` | `401` | ✅ | ✅ |
| `GET /alerts`, `/alerts/active`, `/alerts/{id}` | `401` | ✅ | ✅ |
| `GET /alert-rules` | `401` | ✅ | ✅ |
| `POST` / `PUT` / `DELETE /alert-rules` | `401` | **`403`** | ✅ |

`/health` stays public and answers one question — is the process alive.
`/status` moves behind auth because it exposes operational detail (poll timing,
last error, agent reachability).

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `SYSWATCH_AUTH_ENABLED` | `true` | Master switch; `false` restores the Sprint 8 anonymous API |
| `SYSWATCH_SESSION_SECRET` | *(none)* | HMAC key for session-token hashing. Required unless `dev_mode` |
| `SYSWATCH_SESSION_TTL` | `28800` | Session lifetime, seconds (8h) |
| `SYSWATCH_DEV_MODE` | `false` | Cookie `Secure` off, a fixed dev secret allowed, dev-friendly headers |
| `SYSWATCH_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Unchanged; now used with `allow_credentials=True` |
| `SYSWATCH_ALERTS_ENABLED` | `true` | Unchanged |

```bash
# development
SYSWATCH_DEV_MODE=true python run.py

# production — fails to start without the secret
SYSWATCH_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
SYSWATCH_CORS_ORIGINS=https://dash.example.com \
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

---

## Commit plan

### Phase A — Lock the agent boundary (C++)

**1. `test(agent): pin the HTTP server to loopback`**
`agent/tests/http_server_bind_tests.cpp`: after `start()`, a connect to
`127.0.0.1:<port>` succeeds; assert the server does not accept on a non-loopback
local address (skip cleanly where the host has only a loopback interface). A
comment in `HTTPServer.cpp` next to the `inet_pton` line states why: the agent
has no authentication, so a non-loopback bind would hand every metric — and the
`/snapshot` surface — to anything on the network, bypassing everything this
sprint adds.
*Done when:* the suite fails if the bind address is changed to `0.0.0.0` /
`INADDR_ANY`.

**2. `docs(agent): record that the bind host is deliberately not configurable`**
`AgentConfig` exposes `serverPort` but no host, on purpose. Note it in the agent
README and `AgentConfig.h`. `main.cpp` already prints `127.0.0.1:<port>` — leave
it.

### Phase B — Authentication domain and password security

**3. `feat: define authentication domain models`**
`app/auth/models.py`: Pydantic `User` (no `password_hash` field — it cannot be
serialized if it does not exist on the model), `Credentials`, `CurrentUser`
(`username`, `role`), `Role` literal (`admin` | `viewer`).

**4. `feat: add the password hashing service`**
`app/auth/password.py`: `hash_password`, `verify_password`, a minimum policy
(length ≥ 12, not all one character class — keep it short and documented),
`DUMMY_HASH` for the user-not-found path. `argon2-cffi` pinned into
`requirements.txt`.
*Tests:* correct password verifies; wrong password does not; the stored string
is not the plaintext and not reversible; `verify_password` against `DUMMY_HASH`
takes comparable time to a real verify.
*Watch out:* nothing in this module may log its argument.

**5. `feat: add user and session database models`**
`AlertRuleRecord`-style `UserRecord` and `SessionRecord` in `app/db/models.py`,
per the schema. `sessions.token_hash` and `users.username` both unique; FK
`ondelete="CASCADE"`.

**6. `feat: add the authentication migration`**
One revision off `0a33e83916fa`. Autogenerate, hand-check the unique indexes and
the cascade survived batch rendering. `alembic check` clean.
*Done when:* `upgrade head` on a Sprint 8 database adds the tables and touches
nothing else; `test_migrations.py` covers it.

**7. `feat: add the session service`**
`app/auth/session.py` + `app/auth/service.py`: `authenticate(username,
password)`, `create_session(user) -> raw_token`, `resolve_session(raw_token) ->
CurrentUser | None` (checks the HMAC hash, `expires_at`, `user.enabled`, user
still exists), `revoke(raw_token)`, `prune_expired()`. `app/repositories/` gains
`UserStore` and `SessionStore`; SQLAlchemy stays there.
*Watch out:* the raw token is generated with `secrets.token_urlsafe`, returned
once, and never stored — only its keyed hash.

### Phase C — Authentication API and lifecycle tests

**8. `feat: add the authentication API`**
`app/api/auth.py`: `POST /auth/login` (JSON body; on success `200` +
`Set-Cookie: session=<token>; HttpOnly; SameSite=Lax; Path=/` and `Secure`
unless `dev_mode`; on failure a generic `401`), `POST /auth/logout` (revokes the
session, clears the cookie, `204`), `GET /auth/me` (`{"username", "role"}`,
`401` when unauthenticated). Registered before the protected routers; no auth
dependency on this router.
*Watch out:* no `Domain` on the cookie. Login and `/auth/me` must never echo the
hash or any settings.

**9. `feat: add a login rate limit`**
An in-process fixed-window counter keyed by client IP (fallback: username),
e.g. 10 attempts / 5 minutes → `429` with `Retry-After`. Resets on restart; not
worker-shared — both acceptable and documented.

**10. `test: cover the authentication lifecycle`**
Valid login sets a cookie; unknown username and wrong password give the same
`401` body; `/auth/me` reflects the session; logout invalidates it; an expired
session is rejected; a tampered token is rejected; a disabled user's live
session stops working; the rate limit trips and recovers.

### Phase D — Protect the backend

**11. `feat: add authentication dependencies`**
`app/auth/dependencies.py`: `require_authenticated_user` (reads the cookie,
calls `resolve_session`, `401` on miss), `require_admin` (that plus
`role == "admin"`, else `403`). `SYSWATCH_AUTH_ENABLED=false` makes both yield a
synthetic admin so the anonymous API still works.

**12. `refactor(tests): shared app and authenticated clients`**
`conftest.py` gains a session-scoped `app`, function-scoped DB reset, and
`anon_client` / `viewer_client` / `admin_client` fixtures (the latter two log in
against a seeded user). The nine API test files drop their module-level
`create_app()` / `TestClient` and take a fixture. No behavioural assertions
change yet.

**13. `feat: protect the backend endpoints`**
`include_router(..., dependencies=[Depends(require_authenticated_user)])` for
status, snapshot(s), hosts, alerts, alert-rules; `require_admin` on the three
alert-rule write routes. `/health` and `/auth` stay open.
*Done when:* every protected route is `401` for `anon_client`; `viewer_client`
gets `403` on rule writes; `admin_client` is unchanged from Sprint 8.

**14. `feat: tighten CORS for credentialed requests`**
`allow_credentials=True`, `allow_methods=["GET","POST","PUT","DELETE"]`,
`allow_headers=["Content-Type"]`, origins from config. A settings validator
rejects `"*"` in `cors_origins`. `test_cors.py` updated: preflight from a
configured origin returns that origin **and** `allow-credentials: true`; an
unconfigured origin gets nothing; `"*"` is refused at startup.

### Phase E — Security hardening and bootstrap

**15. `feat: add the admin bootstrap command`**
`python -m app.auth.create_admin`: prompts with `getpass` (never echoed, never
in history), enforces the password policy, refuses if the username exists
(`--reset-password` to replace the hash), requires the DB to be migrated.
*Done when:* a fresh install path is `alembic upgrade head` → `create_admin` →
log in.

**16. `feat: harden the security configuration`**
A small middleware adds `X-Content-Type-Options: nosniff`, `X-Frame-Options:
DENY`, `Referrer-Policy: no-referrer`, and `Content-Security-Policy: default-src
'none'; frame-ancestors 'none'` to every response. `SYSWATCH_SESSION_SECRET`
enforced at startup (lifespan) when `auth_enabled and not dev_mode`. Confirm
FastAPI runs with `debug=False` so no stack trace reaches a client. `.gitignore`
gains `.env.*` alongside the existing `.env`.

### Phase F — Dashboard authentication

**17. `feat: add the dashboard login page`**
`src/pages/LoginPage.tsx` (+ css), `src/auth/api.ts` with `login`, `logout`,
`getMe`. `api/client.ts`: `credentials: 'include'` on every request; a
module-level `onUnauthorized` callback invoked on a `401` from anything except
the login call itself.
*Watch out:* the login page renders outside `AppShell` and polls nothing.

**18. `feat: add dashboard authentication state`**
`src/auth/AuthContext.tsx`, `useAuth()`. On mount it calls `getMe()` once:
resolved → `{user}`, `401` → `{user: null}`, pending → a full-screen loader (not
the login page — a flash of login on every refresh is wrong). Registers the
client's `onUnauthorized` to drop the user to `null`.

**19. `feat: protect the dashboard routes`**
`src/auth/ProtectedRoute.tsx`. `App.tsx` wraps everything in `<AuthProvider>`;
`routes.tsx` puts `/login` outside the shell and every other route under
`<ProtectedRoute>` (redirect to `/login`, preserving the intended path).
`AppShell` header gains the username and a logout button. `renderWithAuth`
test helper; the route and page tests wrap in it.

**20. `feat: add role-aware alert rule controls`**
The Alerts page rules section: for `admin`, an "Add rule" form and per-row
edit / delete (with a confirm) wired to `createAlertRule` / `updateAlertRule` /
`deleteAlertRule`; for `viewer`, unchanged read-only. A `403` from any of these
surfaces as "Only an admin can change alert rules" rather than a generic error.
*Note:* frontend hiding is not security — commit 13 is what enforces it.

### Phase G — End-to-end and docs

**21. `test: authentication and authorization end to end`**
Backend `test_auth_integration.py`: anonymous → `401` on a protected route;
log in → same route `200`; viewer → rule `POST` `403`; admin → `POST` `201`,
`PUT` `200`, `DELETE` `204`; session expiry mid-flow → `401`; CORS preflight
with credentials. Dashboard: login success and failure, protected-route
redirect and return, logout, a `401` mid-session bouncing to `/login`, viewer
vs admin rule controls.

**22. `docs: document authentication and deployment`**
Backend README: the auth model, the two tables, the endpoints, every new
setting, the `create_admin` flow, and a deployment section (HTTPS termination,
same-origin vs cross-origin cookie/`SameSite`, generating the secret). Dashboard
README: the login flow, `AuthContext`, `ProtectedRoute`, and that the cookie is
browser-managed. Root README ticks Phase 5 *Security hardening* groundwork and
notes the new `app/auth/` tree. Agent README: the loopback guarantee.

*Combinable if implementation overlaps:* 1+2 (agent), 3+4 (domain + password),
5+6 (models + migration), 17+18 (login page + context). Lands around 16–18
commits.

---

## Out of scope, flagged

- **HTTPS / TLS termination.** The backend speaks HTTP; a reverse proxy or the
  deployment terminates TLS. The `Secure` cookie assumes that is in place in
  production — `dev_mode` is the only sanctioned HTTP path.
- **Password reset and email.** No token infrastructure this sprint; an admin
  resets a password with the CLI.
- **MFA / TOTP.** Deferred.
- **A user-management API or UI.** Users are created and modified with the CLI
  and direct DB access. `POST /users`, a roster page, role editing — later.
- **Agent authentication.** The agent stays unauthenticated and loopback-only.
  Giving it a credential is a multi-host-registration concern.
- **Exposing the agent port.** Never, until it has its own auth.
- **Distributed / persistent rate limiting and account lockout.** The in-process
  login counter is enough for a single-worker localhost deployment.
- **Audit logging.** Who logged in when, who changed which rule — worth having,
  not this sprint.
- **Serving the built dashboard from FastAPI.** Still two servers; a
  single-origin production build (which simplifies the cookie story) is a
  deployment sprint.
- **CSRF tokens.** `SameSite=Lax` on the session cookie plus a JSON-only,
  non-form API covers the realistic cases for now; revisit if a cross-origin
  browser deployment lands.
