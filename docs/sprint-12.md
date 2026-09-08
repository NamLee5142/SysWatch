# Sprint 12 — More than one machine

Sprint 11 shipped v0.11.0: alerts that reach a person, and the decision that
agents will push rather than be polled. This sprint implements that decision,
and it is the first sprint whose subject is the product's shape rather than its
features.

The goal is narrow and should stay narrow: **a second machine can be monitored,
and the dashboard can tell the two apart.** Everything that sounds like a fleet
product — grouping, tagging, per-host rules, agent auto-update, a registry — is
out of scope and listed at the end.

---

## Where the seams already are

Worth knowing before planning, because the answer is better than it looks.

**Storage is already multi-host.** `snapshots` carries `host_name` with
`UniqueConstraint("host_name", "collected_at")`, and `SnapshotStore` filters by
host throughout. `alerts` is already per `(rule, host)`. Nothing in the data
layer assumes one machine.

**The API is mostly multi-host.** `/snapshots`, `/snapshots/series`,
`/snapshots/latest` and `/alerts` all take a `host` filter. `/hosts` exists and
returns every host that has reported, with a comment from Sprint 6 saying the
dashboard "should render an empty host selector rather than an error".

**Nothing consumes `/hosts`.** That is the gap. The dashboard reads
`/snapshots/latest` with no host and displays whatever comes back, so with two
machines reporting it shows one of them, alternating, with no indication that
it is doing so. This is the most visible single-host assumption in the product
and it is entirely in the front end.

**There is no HTTP client in the agent.** It has an HTTP *server* -
`HTTPServer.cpp`, hand-rolled on Winsock - and links `ws2_32`. Pushing means
writing a client, and that is the largest single piece of work in this sprint.
It is not a small piece: connect, request framing, response parsing, timeouts,
and failure handling, in C++, against a socket API that reports errors by
`WSAGetLastError()`.

**The poller is shaped for exactly one agent.** `SnapshotPoller` holds one
`agent_url`, one `_last_error`, one `_consecutive_failures`. `/status` reports
`agent: up | down | unknown` in the singular. Both stay, for the local agent,
and neither generalises - which is fine, because push replaces them rather than
extending them.

---

## Decisions

The transport question was settled in
[decisions/0001-agents-push-to-the-backend.md](decisions/0001-agents-push-to-the-backend.md).
Its "what this does not decide" section is most of this sprint's design work,
and each one is answered here so that implementation is not also negotiation.

| Question | Decision | Why |
| --- | --- | --- |
| Credential type | **A bearer token per agent**, in an `Authorization` header | A shared token cannot be revoked for one machine, and a machine that is decommissioned or stolen is exactly when you want to revoke one. Per-agent costs a table and a provisioning step, both of which exist anyway |
| Where it lives on the agent | **`syswatch.env` beside the backend's**, Administrators and SYSTEM only | The installer already writes a restricted config file. A second secret store would be a second thing to get wrong |
| Host identity | **From the credential, not the payload** | `systemInfo.hostName` is self-reported. A token that can write as any host can overwrite any host's history, which turns one compromised agent into a fleet-wide integrity problem. The token names the host; the payload's hostname is recorded but not trusted |
| Enrolment | **Pre-shared: an admin creates the token, the installer is given it** | Self-enrolment means an endpoint that accepts unknown agents, which is a listener that grants storage to strangers. A manual step per machine is affordable at the scale this targets, and it is the reversible choice |
| Transport security | **The agent refuses to push over plain HTTP to a non-loopback address** | The token would otherwise cross the network in clear. Loopback is exempt because the single-machine case is the common one and must keep working with no configuration |
| The local agent | **Keeps its loopback listener, keeps being polled** | Install on one machine, monitor that machine, configure nothing. Push is what a *second* machine needs |
| Ingestion shape | **`POST /api/ingest/snapshot`, one snapshot per request** | Batching is an optimisation for a problem nobody has at one snapshot per host per ten seconds, and it makes retry and idempotency harder to reason about |
| Duplicate pushes | **Rely on the existing unique constraint** | `SnapshotStore.save` already returns `None` rather than raising on `(host_name, collected_at)` collision. A retried push is idempotent today, by accident of a decision made for the poller |
| Buffering | **Bounded, in memory, oldest dropped** | A disk buffer is a second durability story and a second thing to corrupt. Metrics age badly: an hour-old snapshot is worth less than the one being dropped for it |

---

## Commit plan

### Phase A — The backend can receive (commits 1–6)

**1. `feat: agent tokens`**
A table, a store, and HMAC-SHA256 hashing in the shape of `app/auth/session.py`.
Columns: `host_name`, `token_hash`, `created_at`, `last_seen_at`, `enabled`.

*Corrected while implementing:* this said Argon2, reusing `password.py`. Wrong
primitive. A password is low-entropy and verified once at login, so it is worth
40 ms and 64 MiB to store; an agent token is 256 random bits verified on every
push, and Argon2 there lets an unauthenticated caller force that work per
request against the ingestion endpoint - a denial-of-service amplifier in front
of authentication. Hashing under the deployment secret, with a domain separator
so an agent token and a session token can never hash alike.
*Watch out:* the token is shown once at creation and never again, like every
other credential this project issues.
*Done when:* a token can be created, verified and disabled, and the plaintext
appears in no table.

**2. `feat: create an agent token from the command line`**
`python -m app.auth.create_agent_token --host <name>`, in the shape of
`create_admin`. Prints the token once, to stdout, with no `--token` flag to
supply one. `--list`, `--revoke` and `--restore` alongside it: the definition of
done says a token is revocable, and no other interface offers that.
*Done when:* the token never reaches shell history, a log, or the process list.

**3. `feat: authenticate a request as an agent`**
A `require_agent` dependency alongside `require_authenticated_user`. Reads a
bearer token, returns the host it names.
*Watch out:* this is the first credential in the system that is not a session
cookie. `app/auth/` has no logger, and this must not be where one appears.
*Done when:* a valid token resolves to a host, an invalid one is a 401, and a
disabled one is a 401 too.

**4. `feat: an ingestion endpoint`**
`POST /api/ingest/snapshot` behind `require_agent`, into the existing
`SnapshotStore.save`. The host comes from the token; the payload's `hostName`
is stored as reported and ignored for identity.
*Done when:* a snapshot posted with a valid token is readable through
`/snapshots`, and one posted with another host's token cannot overwrite it.

**5. `test: a compromised agent cannot forge another host`**
The security property of commit 4, tested directly rather than implied.
*Done when:* a token for host A posting a payload claiming host B writes a row
for A.

*Folded into commit 4.* `test_the_host_comes_from_the_token_not_the_payload`
and `test_another_hosts_token_cannot_overwrite_a_row` were written there, and
both were checked against a mutation that trusts the payload. A separate commit
would have added a name, not a test.

*What it missed:* forging the *row* is only half. `AlertEngine.evaluate` also
took the host from `snapshot.systemInfo.hostName`, so a pushed snapshot would
have been stored under the credential's host and alerted under whatever name it
claimed - one agent opening and resolving another machine's alerts while its
own rows went elsewhere. Found and fixed in commit 6.

**6. `feat: alerts evaluate on ingestion`**
Today evaluation runs after a successful poll. A pushed snapshot must reach the
same engine, or a remote host is monitored and never alerts.
*Watch out:* the poll path calls `evaluate` on a worker thread; the request
path is a threadpool worker. Neither may let a delivery failure escape into the
response.
*Done when:* a rule fires from a pushed snapshot, and a failed notification
still returns 202 to the agent.

### Phase B — The agent can send (commits 7–12)

**7. `feat: an HTTP client for the agent`**
Connect, send a request, read a response, with a timeout. Winsock, matching
`HTTPServer.cpp`'s style, no new dependency.
*Watch out:* the largest commit in the sprint, and the one most likely to be
two. Response parsing is the half that hides the bugs - chunked encoding can be
refused, but a `Content-Length` that disagrees with the body cannot.
*Done when:* it round-trips against the agent's own server in a test, and
against the backend by hand.

*What it actually cost.* The client itself went roughly as estimated. The
surprise was underneath it: every agent test checks with `assert()`, and CI
builds `-DCMAKE_BUILD_TYPE=Release`, which defines `NDEBUG`, which compiles
`assert()` away. All sixteen suites had been passing by reaching the end of
`main()`. Found by mutating the client to return a truncated body as a success
and watching the test written to catch that still pass; fixed in its own commit
first, because it is not part of the client and the client's tests are worthless
without it.

With assertions running, two real bugs in the new code appeared at once - a
host called `127.example.com` counted as loopback, which commit 9 would have
let a token cross the network in clear to reach; and a refused connection sat
out the whole timeout on Windows, because Winsock reports a failed connect in
select's *exception* set rather than its write set. Neither was reachable by
reading the code, and neither would have failed CI as it stood.

**8. `feat: push a snapshot to a configured backend`**
A destination URL and a token in the agent's config. Unset means today's
behaviour exactly: collect, serve on loopback, push nothing.
*Done when:* an agent with a backend configured appears in `/hosts` on another
machine.

**9. `feat: refuse to push a token over plain http`**
The decision above, enforced in the agent rather than documented. Loopback
exempt.
*Watch out:* "is this loopback" is a real check, not a string comparison
against `localhost` - `127.0.0.2` and `[::1]` are loopback too.
*Done when:* an `http://` URL naming anything but loopback is refused at
startup, with a message that names the setting.

**10. `feat: buffer snapshots while the backend is unreachable`**
Bounded, oldest dropped, with the size a constant and a comment about why that
number.
*Done when:* a backend stopped for five minutes loses no more than the buffer's
worth, and the agent's memory does not grow while it is down.

**11. `feat: the agent reads a configuration file`**
Phase 1's unticked "configuration loader", needed now because there is finally
something to configure. Still no `--bind`.
*Done when:* the backend URL and token come from a file the installer writes,
and an absent file means today's defaults.

**12. `fix: whatever pushing to a real backend finds`**
Deliberately vague, in the shape of Sprint 11's commit 12. Two components in
two languages agreeing over a socket for the first time will find something.
*Done when:* a C++ agent on one machine and a Python backend on another have
exchanged snapshots for an hour.

### Phase C — Seeing more than one machine (commits 13–17)

**13. `feat: a host selector`**
`/hosts` has existed since Sprint 6 and nothing has ever called it.
*Done when:* choosing a host changes what every page shows, and the choice
survives a reload.

**14. `feat: scope every page to the selected host`**
Overview, CPU, Memory, Disk, Network, Processes, History. Each already accepts
a `host` parameter; none passes one.
*Watch out:* `/status` reports the *local* agent and does not become per-host.
A pushing agent's health is "when did it last push", which is a different
question and is commit 15.
*Done when:* two hosts reporting produce two distinct dashboards, and no page
silently shows a mixture.

**15. `feat: report a host as stale rather than absent`**
A host that stops pushing currently just stops appearing to change. Last-seen,
and a threshold past which the dashboard says so.
*Watch out:* the alert for this belongs to a later sprint. This is display, not
notification, and conflating them makes both worse.
*Done when:* an agent stopped for ten minutes is visibly stale rather than
quietly stale.

**16. `feat: show which host an alert belongs to`**
`hostName` is on every alert already and the table does not show it.
*Done when:* two hosts breaching the same rule are two rows, distinguishable.

**17. `chore: install an agent that pushes`**
`Install-SysWatch.ps1` gains `-BackendUrl` and `-AgentToken`, writing them to
the restricted config. Absent means today's single-machine install.
*Done when:* a clean machine with those two parameters appears in another
machine's dashboard, and one without them behaves exactly as v0.11.0 did.

### Phase D — Writing it down (commits 18–19)

**18. `docs: document multi-host installation`**
`deployment.md` gains a second-machine section: create a token, install with
it, what to check. The backend README gains the ingestion endpoint and the
agent settings.
*Done when:* adding a second machine needs no reading of source.

**19. `docs: record what pushing cost`**
A second decision record, superseding nothing, describing what 0001 got wrong.
Something always is.
*Done when:* sprint 13 can see which assumptions held.

---

## Definition of done

1. Two machines report to one backend, and the dashboard tells them apart.
2. An agent token is per host, revocable, and never recoverable after creation.
3. A token for one host cannot write another host's history.
4. The agent refuses to send a token over plain HTTP off loopback.
5. A single-machine install is unchanged: no token, no URL, no new steps.
6. A backend outage loses at most the buffer, and the agent survives it.
7. Every suite green on all four CI jobs, including PostgreSQL.
8. The install workflow covers both a plain install and a pushing one.
9. `deployment.md` describes adding a second machine end to end.
10. Verified between two real machines, not two processes on one.

---

## Out of scope, flagged

- **Host groups, tags, or per-group rules.** Rules are global and a fleet
  eventually needs otherwise. Not before a fleet exists.
- **Agent auto-update.** A remote code-execution channel by construction, and
  it deserves a sprint and a threat model rather than a commit.
- **Remote configuration.** The same objection, less sharply.
- **Self-enrolment or discovery.** An endpoint that accepts unknown agents is
  the opposite of this sprint's identity decision.
- **Removing the poller.** It is how the local agent works with no
  configuration, and that is the common case.
- **TLS termination in the application.** Still a reverse proxy's job. Commit 9
  refuses plain HTTP; it does not provide the alternative.
- **Disk-backed buffering, batching, compression.** Optimisations for volumes
  this does not have.
- **A migration path for the alert engine to run centrally per host.** It
  already does. Worth confirming rather than assuming, which is commit 6.

---

## Estimate

Nineteen commits planned. Sprint 10 ran at 1.8x its plan and Sprint 11 at 1.4x,
and this sprint has an unknown Sprint 11 did not: an HTTP client written in C++
against Winsock, and the first time two components in two languages have had to
agree over a network. Commit 7 could be three commits and commit 12 could be
five.

**30–40 is the honest expectation**, and the first real risk to that number is
commit 7, not the security work.
