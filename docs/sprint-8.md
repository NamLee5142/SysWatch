# Sprint 8 — Alert Engine

**Goal:** evaluate live snapshots against configurable thresholds, persist alert
state and history, serve alerts through the API, and surface active alerts in the
dashboard.

```text
                              ┌──────────────┐
Agent → SnapshotPoller ──────▶│ store snapshot│
        (successful tick)     └──────────────┘
              │
              ▼
        AlertEngine ── reads enabled rules ──▶ alert_rules
              │
              ├─ Rule 1 → not violated
              ├─ Rule 2 → violated  ──▶ open / update alert
              └─ Rule 3 → recovered ──▶ resolve alert
                                            │
                                            ▼
                                          alerts  ──▶  /alerts, /alerts/active
                                                            │
                                                            ▼
                                                     Dashboard /alerts + 🔔
```

**The load-bearing principle:** the agent collects facts, the backend decides
whether those facts are an alert. No threshold, operator or severity ever reaches
the C++ agent, so alert policy is reconfigurable without a rebuild.

## Starting point

Sprint 7 finished the snapshot pipeline for six metrics (`cpu`, `memory`,
`disk`, `processes`, `net_sent`, `net_recv`). This sprint adds a consumer of that
pipeline, not a new source. It is almost entirely additive, but seven existing
facts narrow at the point of contact:

1. **The poller throws the snapshot away.** `SnapshotPoller.poll_once()` does
   `await asyncio.to_thread(self._service.get_snapshot)` and discards the return
   value — the evaluator needs that object. And evaluation must run **only** on
   the success branch: not on `LookupError` (agent has nothing yet), not on the
   `except Exception` branch (agent unreachable or malformed). Evaluating there
   would fire alerts caused by infrastructure failure, which is `/status`'s job
   to report, not the alert engine's.

2. **CORS is `allow_methods=["GET"]`.** `create_app()` locks the middleware to
   GET. Every `POST`/`PUT`/`DELETE` to `/alert-rules` is blocked by the browser
   before it reaches FastAPI — the same class of bug Sprint 6 fixed for reads.
   Widening it also turns an unauthenticated API from read-only into read-write:
   fine on `127.0.0.1`, but it must not reach a network before Phase 4 auth, and
   that constraint is now sharper.

3. **The dashboard API client is GET-only.** `request()` in `api/client.ts` is a
   bare `fetch` with no `method` or `body`; every exported helper is a GET. Write
   support is new plumbing, and the `ApiError` / `NetworkError` split has to
   extend to it so a rejected `POST` still renders differently from an offline
   backend.

4. **Nothing seeds rules.** A fresh `syswatch.db` has zero `alert_rules`, so the
   engine evaluates nothing and the feature looks broken on first run. Default
   rules need seeding — and they must stay deleted once a user removes them, not
   reappear on the next migration or restart.

5. **`Metric` is a snapshot concept.** `Literal["cpu", "memory", "disk",
   "processes", "net_sent", "net_recv"]` lives in `app/models/snapshot.py`, and
   `metric_expression()` in `snapshot_store.py` is **SQL over `SnapshotRecord`**.
   Rules should reuse that `Metric`, but the engine evaluates a live Pydantic
   `Snapshot`, so it needs a Python-side twin of `metric_expression` — the same
   way `Snapshot.from_payload` sits beside `Snapshot.from_record`.

6. **Alert identity versus poll cadence.** The poller ticks every 10s. A CPU
   alert that stays firing for an hour is **one row, updated** — not 360 rows.
   The engine needs an "open alert per (rule, host)" lookup and an explicit
   OK/FIRING state machine, and that machine is what the tests must pin down.

7. **Rule lifecycle destroys history context.** `DELETE /alert-rules/{id}` and
   editing a threshold both erase the conditions a past alert fired under.
   The rule's identity has to be denormalised onto the alert row at trigger
   time — the same reasoning that keeps `os_version` on the snapshot rather than
   in a `hosts` table.

No new dependencies, backend or frontend. SQLAlchemy, Alembic and FastAPI are
already in `requirements.txt`; `usePolling`, the skeleton primitives and the
error components already exist in the dashboard.

## Locked decisions

| Decision | Final choice | Rationale |
| --- | --- | --- |
| Where policy lives | **Backend only** | The agent collects facts; thresholds are configuration, changeable without a rebuild. |
| Rule metric type | **Reuse `Metric` from `app/models/snapshot.py`** | Six metrics already defined, unit-tagged and charted. A parallel enum would drift. |
| Evaluation input | **The live `Snapshot` object, in the poller** | Deterministic and unit-testable without a database. Not SQL over stored rows. |
| Operators | **`gt`, `gte`, `lt`, `lte`** | Covers every example rule. Equality on a float metric is not useful. |
| States | **`ok`, `firing`** | No `acknowledged` / `silenced` yet — that is notification-delivery scope. |
| Severity | **`info`, `warning`, `critical`** | Lowercase string literals, like `agent` states. Ordering is for sorting only. |
| When evaluation runs | **After a successful poll, never after a failed one** | Friction point 1. Agent-down is `/status`, not an alert storm. |
| Rules read per tick | **`AlertRuleStore.enabled_rules()` every evaluation** | A new rule takes effect within one interval, no restart. A cheap indexed SQLite read, the same trade the dashboard already makes. |
| One open alert per (rule, host) | **Enforced by the engine, found by query** | `alerts` is append-plus-update: a violation with no open alert inserts; one with an open alert updates `value` / `last_seen_at`; recovery sets `state=ok` and `resolved_at`. |
| Rule deletion | **Hard delete; `alerts.rule_id` is a nullable FK, `ON DELETE SET NULL`** | History outlives the rule. |
| Alert row is self-describing | **Denormalise `rule_name`, `metric`, `operator`, `threshold`, `severity` onto the alert at trigger time** | Friction point 7. A past alert shows the threshold that was in force when it fired, even after the rule is edited or deleted. |
| Disabling a rule | **Resolves its open alert on the next tick** | A disabled rule with a stuck red alert is worse than no rule. |
| Metric absent on a snapshot | **Skip the rule that tick — neither fire nor resolve** | A pre-Sprint-7 agent sends no `processes`; that is missing data, not a recovery. |
| Dashboard rule editing | **API only this sprint; the page lists rules read-only** | The sprint deliverable is *seeing* alerts. A full rule editor is a follow-up. |
| Indicator transport | **Polling `/alerts/active` on the existing interval** | No WebSocket/SSE. Consistent with every other live value in the app. |

## Schema

Two new tables. One Alembic revision for the tables, a second for the seed data
(so a user's later `DELETE` is not undone by re-running migrations). Batch mode,
named per the metadata convention, as in Sprint 5.

### `alert_rules`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `name` | text, not null | Human label, e.g. "CPU critical" |
| `metric` | text, not null | One of the six `Metric` values |
| `operator` | text, not null | `gt` \| `gte` \| `lt` \| `lte` |
| `threshold` | float, not null | Compared in the metric's own unit (percent, count, bytes/sec) |
| `severity` | text, not null | `info` \| `warning` \| `critical` |
| `enabled` | boolean, not null, default true | Disabled rules are skipped and resolve their open alerts |
| `created_at` | datetime (UTC) | |
| `updated_at` | datetime (UTC) | |

### `alerts`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer PK | |
| `rule_id` | integer FK → `alert_rules.id`, nullable, `ON DELETE SET NULL` | Null once the rule is deleted |
| `rule_name` | text, not null | Snapshot of the rule at trigger time |
| `metric` | text, not null | " |
| `operator` | text, not null | " |
| `threshold` | float, not null | " |
| `severity` | text, not null | " |
| `host_name` | text, not null | From `systemInfo.hostName` |
| `state` | text, not null | `ok` \| `firing` |
| `value` | float, not null | Most recent evaluated metric value |
| `triggered_at` | datetime (UTC) | When the alert opened |
| `resolved_at` | datetime (UTC), nullable | When it returned to `ok` |
| `last_seen_at` | datetime (UTC) | Most recent tick that evaluated this alert |

Indexes:

- `ix_alerts_host_name_state` — the "open alert per (rule, host)" lookup and
  `GET /alerts/active` both filter on it.
- `ix_alerts_rule_id` — resolving a rule's alerts when it is disabled or deleted.
- `ix_alerts_triggered_at` — `GET /alerts` history, newest first.

## Rule and state model

```text
        no open alert
              │  rule violated
              ▼
  ┌────────────────────────┐   still violated (every tick)
  │  INSERT alert           │◀───────────────────────────┐
  │  state = firing         │                            │
  │  triggered_at = now     │   UPDATE value, last_seen_at │
  └───────────┬────────────┘───────────────────────────┘
              │  metric back to normal, OR rule disabled/deleted
              ▼
  ┌────────────────────────┐
  │  UPDATE alert           │
  │  state = ok             │
  │  resolved_at = now      │
  └────────────────────────┘
```

The sequence the tests exist to protect:

| Tick | CPU | Rule `cpu gt 90` | Result |
| --- | --- | --- | --- |
| 1 | 95% | violated, no open alert | **one** new row, `firing` |
| 2 | 96% | violated, open alert | same row, `value` → 96 |
| 3 | 92% | violated, open alert | same row, `value` → 92 |
| 4 | 80% | not violated, open alert | same row, `state` → `ok`, `resolved_at` set |
| 5 | 97% | violated, no open alert | a **new** row, `firing` |

## Page → data map

| Page / element | Reads | Notes |
| --- | --- | --- |
| Alerts page — active table | `GET /alerts/active` | Severity, name, host, current value, threshold, since, state |
| Alerts page — recent/resolved | `GET /alerts?state=ok&limit=50` | History, newest first |
| Alerts page — rules list | `GET /alert-rules` | Read-only this sprint |
| App shell — 🔔 indicator | `GET /alerts/active` | Count badge, links to `/alerts`, polled on `POLL_INTERVAL_MS` |

---

## Commit plan

### Phase A — Domain model

**1. `feat: define alert domain models`**
`app/models/alert.py`: `Severity`, `AlertState`, `Operator` literals; `AlertRule`,
`AlertRuleCreate`, `AlertRuleUpdate`, `Alert`, `AlertPage` (`items` + `count`,
like `SnapshotPage`). `metric` is the `Metric` literal imported from
`app/models/snapshot.py`, not redefined.
*Watch out:* validate on the way in — non-empty `name`, finite `threshold`,
`metric` in range, `operator` in range. A bad rule must be a `422` at
`POST /alert-rules`, never a row that makes the engine raise every tick.

### Phase B — Evaluation engine

**2. `feat: add alert rule evaluator`**
`app/alerts/evaluator.py`: `snapshot_metric_value(metric, snapshot)` — the
Python twin of `metric_expression()`, reading the Pydantic model
(`cpu` → `cpuInfo.usagePercent`, `memory` → `100 * usedMB / totalMB`,
`disk` → `100 * (totalGB - freeGB) / totalGB`, `processes` →
`processInfo.count`, `net_sent`/`net_recv` → summed interface rates). Returns
`None` when the metric's source is absent. `is_violated(rule, value)` applies the
operator. Pure, no I/O.
*Watch out:* `disk` is **used** percent here, matching the series axis — the
"disk almost full" rule is `disk gt 90`, not a free-space rule. Say so in the
docstring.
*Done when:* a table-driven test covers every metric and every operator,
including the `None` path.

**3. `feat: add alert engine`**
`app/alerts/engine.py`: `AlertEngine(rule_store, alert_store)` with
`evaluate(snapshot) -> EvaluationSummary`. For each enabled rule: compute the
value, look up the open alert for `(rule.id, host_name)`, and apply the state
machine above. Disabled/absent rules with an open alert resolve it. No direct
SQLAlchemy — only the two stores.
*Done when:* the five-tick sequence in "Rule and state model" passes as one test,
asserting the row count as well as the states.

### Phase C — Persistence

**4. `feat: add alert database models`**
`AlertRuleRecord` and `AlertRecord` in `app/db/models.py`, per the schema above —
FK with `ondelete="SET NULL"`, the three indexes, `created_at`/`updated_at`
server defaults. Names flow through the existing `NAMING_CONVENTION`.

**5. `feat: add alert repositories`**
`app/repositories/alert_store.py`: `AlertRuleStore` (`list`, `get`, `create`,
`update`, `delete`, `enabled_rules`) and `AlertStore` (`open_alert(rule_id,
host)`, `open_new`, `touch`, `resolve`, `query`, `active`, `get`). SQLAlchemy
stays in this file, like `SnapshotStore`. Export both from
`app/repositories/__init__.py`.
*Watch out:* `open_alert` must order by `id DESC` and take the first — a
`(rule, host)` pair can have many historical rows and only the newest may be open.

**6. `feat: add alert tables migration`**
One Alembic revision, `down_revision` = the current head. Autogenerate, then
hand-check the FK `ondelete` and the indexes survived batch rendering.
*Done when:* `alembic upgrade head` on a database already at
`c69cb3ded3fd` with snapshot rows in it succeeds and leaves those rows untouched.

**7. `feat: seed default alert rules`**
A **separate** data-only revision inserting the starter set: `cpu gt 90` warning,
`cpu gt 95` critical, `memory gt 90` warning, `disk gt 90` warning,
`processes gt 500` info, `net_recv gt <n>` info. `downgrade` deletes exactly
those.
*Watch out:* keyed insert by `name`, `INSERT` only if absent, so re-running does
not resurrect a rule the user deleted.

### Phase D — Integration

**8. `feat: evaluate alerts after a successful poll`**
Capture the snapshot in `poll_once()`; on the success branch only, call
`AlertEngine.evaluate` through `asyncio.to_thread`, logging and swallowing any
failure exactly like `prune_if_due` — a broken engine must not stop collection.
`create_poller()` in `main.py` builds the engine from the stores. New setting
`SYSWATCH_ALERTS_ENABLED` (default `true`).
*Done when:* with the agent up and CPU pinned, an alert row appears within one
poll interval; with the agent stopped, no alert row appears and `/status` still
flips to `down`.

**9. `test: cover alert state transitions`**
The five-tick sequence; repeated firing not creating rows; multiple rules on one
snapshot; multiple severities; a disabled rule resolving its open alert; the
metric-absent skip; `resolved_at` set once and not moved by a later tick. Against
a `tmp_path` SQLite database, never the real file.

### Phase E — API

**10. `feat: add alert read API`**
`app/api/alerts.py`: `GET /alerts` (filters `host`, `state`, `rule_id`, `since`,
`until`, `limit`≤1000, `offset`; returns `{items, count}`), `GET /alerts/active`
(`state = firing`, newest `triggered_at` first), `GET /alerts/{id}` (`404` when
missing). Reuse the `_validate_window` 422 pattern. Register in `create_app()`.

**11. `feat: add alert rule management API`**
`app/api/alert_rules.py`: `GET /alert-rules`, `POST` (`201`), `PUT /{id}`,
`DELETE /{id}` (`204`). `404` for a missing id, `422` for an invalid body. Add
`POST`, `PUT`, `DELETE` to `allow_methods` in the CORS middleware.
*Watch out:* note in the code and the README that this is the first write path on
an unauthenticated API — acceptable on localhost, gated before Phase 4.

### Phase F — Dashboard

**12. `feat: add write support to the API client`**
`request()` gains `method` and `body`; `ApiError` / `NetworkError` handling
covers them. New helpers: `getAlerts`, `getActiveAlerts`, `listAlertRules`,
`createAlertRule`, `updateAlertRule`, `deleteAlertRule`. Mirror `Alert`,
`AlertRule`, `AlertPage`, `Severity`, `Operator`, `AlertState` into
`api/types.ts`.

**13. `feat: add the Alerts page and route`**
`Alerts` nav item in `AppShell` and `routes.tsx`. Active-alerts table (severity,
name, host, current value, threshold, `triggered_at` as relative time via
`RelativeTime`, state), a resolved/recent section, and a read-only rules list.
Loading via `TableSkeletonRows`, error via `SnapshotErrorMessage`, and an empty
state ("No active alerts") that is a success, not an error.

**14. `feat: add the alert indicator to the app shell`**
A 🔔 with the active count in the header, polled on `POLL_INTERVAL_MS`, linking
to `/alerts`. Zero active alerts renders the bell quiet, not hidden — a missing
indicator and "no alerts" look the same otherwise.

### Phase G — Testing and docs

**15. `test: expand alert API and dashboard coverage`**
Backend: rule validation and CRUD, `404` paths, the legacy-database upgrade from
`c69cb3ded3fd`, a CORS preflight for `POST /alert-rules` returning the configured
origin. Dashboard: client write paths and error mapping, `AlertsPage` in
loading / empty / populated / error, and the indicator badge count from a mocked
`/alerts/active`.

**16. `docs: document the alert engine`**
Root README ticks Phase 4 *Alert engine*. Backend README gains the two tables,
the six endpoints, `SYSWATCH_ALERTS_ENABLED`, and the evaluation-after-success
rule. Dashboard README gains the Alerts page and the indicator. Include the
snapshot → engine → SQLite → REST → dashboard diagram and the supported
metric/operator matrix.

*Combinable if implementation overlaps:* 6+7 (both migrations), 10+11 (one alert
router module), 2+3 (evaluator and engine in one pass). That lands the sprint at
roughly 12–14 commits.

---

## Out of scope, flagged

- **Notification delivery.** Email, webhooks, Slack. The `alerts` table is the
  substrate for it; this sprint does not send anything anywhere.
- **Alert acknowledgement / silencing.** No `acknowledged` state, no snooze. The
  two-state machine is deliberate.
- **A rule editor in the dashboard.** CRUD is API-only; the page lists rules
  read-only. A form with live metric/operator validation is a follow-up.
- **Per-rule evaluation windows / "for 5 minutes" durations.** A rule fires on
  the first violating sample. Flap damping (hysteresis, a sustained-breach
  requirement) is a later refinement.
- **Authentication on the write endpoints.** `/alert-rules` mutation is
  unauthenticated over CORS — localhost only, and it must not reach a network
  before Phase 4, same as every prior sprint's note.
- **Alerting on agent reachability.** "Agent down" stays a `/status` concern.
  Turning it into an alert needs a source other than a successful snapshot and is
  its own design.
