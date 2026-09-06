# Sprint 11 — Alert Delivery & Fleet Groundwork

## Goal

Make the alert engine tell somebody, and give an operator a way to stop being
told. Sprint 8 built the evaluator and Sprint 10 made the whole thing
deployable; between them an alert still goes no further than a database row and
fires until the condition clears.

Alongside that, three pieces of groundwork for multi-host — chosen because each
one is worth having on a single machine too. Anything that only pays off in a
fleet is deliberately absent: it would be built against guesses about a design
that has not been made yet.

## Starting point

Nine things that are true today.

1. **Alerts stop at the database.** There is no `smtplib`, no webhook, no
   outbound call anywhere in `backend/app/`. `AlertEngine` opens and resolves
   rows and the dashboard renders them. Nothing reaches a person who is not
   already looking at the page, which is the one case alerting exists for.

2. **A firing alert fires forever.** `AlertRecord` has `state`, `triggered_at`,
   `resolved_at` and `last_seen_at`, and no acknowledgement. The only exit is
   the metric recovering. A disk that is legitimately at 85% because that is
   how much data there is will alert every evaluation until somebody buys a
   disk.

3. **There is no way to silence a rule.** Not during maintenance, not while a
   fix is in progress, not at all. The available responses are "watch it fire"
   and "disable the rule and hope somebody re-enables it".

4. **Log timestamps are local; database timestamps are UTC.** `_utcnow()` is
   used correctly throughout the data layer, and `logging.Formatter` uses local
   time. The same instant appears seven hours apart on this machine. It misled
   the author of Sprint 10 during Sprint 10's own testing, with the data on
   screen.

5. **"Storage is portable" is an untested claim.** Sprint 10's out-of-scope
   note says `SnapshotStore` and friends are what keep PostgreSQL a
   configuration change. The shape supports it — `session.py` guards every
   pragma behind `_is_sqlite()`, `backup.py` refuses a non-SQLite URL outright
   — but no SQL in this project has ever run against PostgreSQL.

6. **`requirements.txt` ships `pytest` and `respx`.** The installer builds
   production virtual environments from it, so every deployment carries a test
   framework it will never run.

7. **CI runs the backend suite twice** for a branch with an open pull request,
   once for `push` and once for `pull_request`.

8. **Both tag spellings exist** for 0.5 through 0.9 — `v.0.7.0` and `v0.7.0`
   name the same commit. Anything that reads tags sees two releases.

9. **The multi-host transport is undecided.** It is the first question of the
   next sprint and it determines the agent's entire security surface, so it is
   answered here, on paper, before anyone writes code against a guess.

## Locked decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Notification transports | **SMTP and webhook, both optional, both off by default** | Covers "tell a person" and "tell a system" with no dependency on either. |
| Delivery failures | **Logged and swallowed** | The same rule persistence already follows: a broken mail server must not stop the poller collecting. |
| Notifier shape | **One interface, implementations wired explicitly** | Two senders do not need a plugin system, and a registry would be the speculative half of the design. |
| What is delivered | **State changes only, above a configured severity** | A notification per evaluation is a mail loop. Opened and resolved are events; still-firing is not. |
| Acknowledgement | **Columns on `alerts`, not a new table** | It is an attribute of the alert, and a join buys nothing. |
| Silencing | **Per rule, with an expiry** | Silencing one alert leaves the next identical one to fire. An expiry means a silence cannot be forgotten. |
| Acknowledged alerts | **Stay open, stop notifying** | Hiding them would lose the state an operator acknowledged. |
| Log timestamps | **UTC, with the offset in the format** | One clock across logs, database and hosts. The offset makes it unambiguous rather than merely consistent. |
| PostgreSQL | **A CI job, not a supported deployment** | The claim gets tested; SQLite stays what ships and what is documented. |
| Dev dependencies | **`requirements-dev.txt`** | The installer reads `requirements.txt`; what it reads should be what production needs. |
| Agent transport | **Decided in writing this sprint, implemented next** | The decision costs nothing now and is expensive to reverse later. |

## Push or poll

The next sprint's first question, answered here because everything else about
it follows.

Today the backend polls one agent at `127.0.0.1:8080` every ten seconds. The
agent binds loopback and has no authentication, and Sprint 9's whole security
argument rests on that: it is reachable from the machine it monitors and
nowhere else.

A fleet breaks that arrangement in one of two ways.

**Polling N agents** keeps the backend's model. Every agent must then listen on
a routable address, which means every agent needs authentication, TLS, and a
firewall rule — and the backend needs to reach each one, which fails behind NAT
and on any machine that comes and goes.

**Agents pushing** inverts it. The agent opens an outbound connection to the
backend and posts snapshots. No inbound port, no firewall rule, no reachability
requirement, and the credential lives on the agent where it can be provisioned
at install time. The backend gains an authenticated ingestion endpoint, which
is a thing it can already almost do: there is exactly one write path today,
`SnapshotService._persist` into `SnapshotStore.save`.

**Push wins**, and the reasons are worth writing down because they are not
symmetric: polling requires opening a port on every monitored machine, and this
project has spent two sprints arguing that the agent's port should never be
open. The poller does not disappear — it stays for the local agent, which is
the common case and the one that works with no configuration at all.

Nothing in this sprint implements it. The point is that Sprint 12 starts from a
decision rather than an argument.

## Configuration after this sprint

| Variable | Default | Purpose |
| --- | --- | --- |
| `SYSWATCH_NOTIFY_MIN_SEVERITY` | `warning` | Below this, alerts are stored and not sent |
| `SYSWATCH_SMTP_HOST` | *(none)* | Unset disables mail entirely |
| `SYSWATCH_SMTP_PORT` | `587` | |
| `SYSWATCH_SMTP_USERNAME` | *(none)* | |
| `SYSWATCH_SMTP_PASSWORD` | *(none)* | Never logged, like every other secret |
| `SYSWATCH_SMTP_FROM` | *(none)* | |
| `SYSWATCH_SMTP_TO` | *(none)* | Comma-separated, like `CORS_ORIGINS` |
| `SYSWATCH_WEBHOOK_URL` | *(none)* | Unset disables webhooks entirely |

Both transports are off unless configured, and a configuration that is
half-filled — a host with no recipients — is refused at startup rather than
discovered when an alert fails to arrive.

## Commit plan

### Phase A — Delivery

**1. `feat: add a notifier for alert state changes`**
An interface with one method, and a logging implementation behind it. The
logging one is not a placeholder: on a machine with no mail server it is the
delivery mechanism, and it makes every later test able to assert on what would
have been sent.
*Done when:* an alert opening writes a line naming the rule, the host and the
value, and resolving writes another.

**2. `feat: send alerts over SMTP`**
Configured host, credentials, recipients. Subject carries severity, rule and
host; body carries the value, the threshold and when it started.
*Watch out:* the password must never reach a log. `app/auth/` has no logger at
all for this reason; the notifier needs the same discipline.
*Done when:* a fake SMTP server receives one message per state change and none
per evaluation.

**3. `feat: post alerts to a webhook`**
JSON, the same shape the API already returns for an alert, so a consumer does
not learn a second schema.
*Done when:* a stubbed endpoint receives opened and resolved, and a non-2xx
response is logged without disturbing the poller.

**4. `feat: refuse a half-configured notifier`**
An SMTP host with no recipients, a webhook URL that is not a URL. Alongside the
existing startup checks in `app/security.py`.
*Done when:* each partial configuration names what is missing and the process
does not start.

**5. `test: deliver nothing when delivery breaks`**
A mail server that refuses connections, a webhook that times out, a notifier
that raises. Collection, evaluation and storage must all continue.
*Done when:* with every transport failing, snapshots still accumulate and
alerts still open and resolve in the database.

### Phase B — Living with alerts

**6. `feat: acknowledge an alert`**
`acknowledged_at` and `acknowledged_by` on `alerts`, a migration, and
`POST /api/alerts/{id}/acknowledge` behind an authenticated session.
*Done when:* acknowledging records who and when, and the alert stays open.

**7. `feat: silence a rule until a time`**
`silenced_until` on `alert_rules`, and an endpoint taking a duration. Admin
only, like every other rule mutation.
*Done when:* a silenced rule still evaluates and still records, and sends
nothing until the expiry passes.

**8. `feat: stop notifying about acknowledged and silenced alerts`**
The point of the previous two commits. A resolution still notifies — the end of
an incident is news even when the start was acknowledged.
*Done when:* an acknowledged alert re-firing sends nothing, and its resolution
sends once.

**9. `feat: acknowledge and silence from the dashboard`**
A button on an alert, a menu on a rule, and a visible marker for both states.
Admin-only controls hidden from a viewer, as the existing pages already do.
*Done when:* a viewer sees the state and cannot change it.

### Phase C — Groundwork

**10. `fix: log in UTC`**
A formatter with an explicit offset. Both the backend and the agent, so a
support bundle from one machine has one clock in it.
*Watch out:* the agent's `Logger` formats its own timestamps in C++; this is
two changes, not one.
*Done when:* a log line and the `collected_at` of the snapshot it describes
name the same instant.

**11. `ci: run the backend suite against postgresql`**
A service container and a second matrix axis. SQLite stays the default and the
only supported deployment; this exists to test the claim that the storage
boundary is real.
*Done when:* the suite runs green against both, or the SQLite-isms it finds are
listed in the next commit.

**12. `fix: whatever postgresql finds`**
Deliberately vague, because the point of commit 11 is that nobody knows yet.
Likely candidates: `VACUUM INTO` in the backup command, which already refuses a
non-SQLite URL; anything relying on SQLite's type affinity; the boolean and
datetime handling in migrations.
*Done when:* both engines pass, and anything genuinely SQLite-only is documented
rather than worked around.

### Phase D — Papercuts

**13. `chore: split development dependencies out of requirements`**
`requirements-dev.txt` for `pytest` and `respx`. The installer and the release
archive read `requirements.txt`; CI reads both.
*Done when:* a production virtual environment has no test framework in it, and
CI still runs.

**14. `ci: stop running the same tests twice`**
`push` narrowed to `main`. Pull request checks are what gate a merge and they
already run unfiltered.
*Done when:* a push to a branch with an open pull request runs each suite once.

**15. `chore: remove the duplicate release tags`**
Delete the `v.0.5.0` spellings, locally and on the remote, keeping `v0.5.0`.
*Done when:* one tag names each release.

**16. `docs: correct the phase 1 roadmap`**
CMake, the CPU, memory and disk collectors and JSON serialization are all done
and unticked. The cross-platform layer and the secure communication module are
not, and stay unticked.
*Done when:* the checklist matches the repository.

### Phase E — Writing it down

**17. `docs: decide how agents will reach the backend`**
The push-or-poll argument above, as a decision record next to the sprint plans,
with the alternatives and why they lost.
*Done when:* Sprint 12 can start implementing rather than deciding.

**18. `docs: document notifications and the alert lifecycle`**
`docs/deployment.md` gains configuring mail and webhooks, and what each startup
refusal means. The backend README gains the new endpoints and settings.
*Done when:* configuring alert delivery needs no reading of source.

*Combinable:* 2+3 (one interface, two implementations), 6+7. Lands around
18–25 commits planned; Sprint 10 ran at 1.8× its plan and every commit in
Phase C is an unknown, so 30–35 is the honest expectation.

---

## Out of scope, flagged

- **Multi-host anything.** No agent identity, no credentials, no registration,
  no `hosts` table, no ingestion endpoint. Sprint 12 decides its own shape from
  the decision record, not from scaffolding guessed at here.
- **A user management UI.** Accounts are still `python -m app.auth.create_admin`.
  Real work, and this sprint is full.
- **Notification templating or per-rule routing.** One recipient list, one
  webhook. Routing is a fleet concern and follows multi-host.
- **Escalation, on-call schedules, deduplication windows.** A monitoring product
  eventually needs them; a single machine does not.
- **SMS, Slack, PagerDuty.** A webhook reaches all of them through anything that
  forwards, and each native integration is a dependency and a credential.
- **PostgreSQL as a deployment.** Tested in CI, not documented, not installed,
  not supported. The migration story stays written down and unexercised.
- **Alert history retention.** `snapshots` is pruned; `alerts` is not, and at
  one host that is fine for a long time.
- **TLS.** Still a reverse-proxy responsibility, and still not automated.
