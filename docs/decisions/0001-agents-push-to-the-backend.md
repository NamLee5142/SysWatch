# 0001 - Agents push to the backend

**Accepted**, sprint 11. Nothing in sprint 11 implements it; the point is that
sprint 12 starts from a decision rather than an argument.

## Context

SysWatch monitors one machine. The backend polls a single agent at
`SYSWATCH_AGENT_BASE_URL`, default `http://127.0.0.1:8080`, every
`SYSWATCH_POLL_INTERVAL_SECONDS`, default 10.

The agent binds `127.0.0.1` and has no authentication of any kind. Those two
facts are load-bearing and depend on each other: the agent serves every metric
it collects, plus a process list, to anyone who asks, and what makes that
acceptable is that "anyone" means a process already running on the monitored
machine. There is deliberately no `--bind` flag - `runtime::parseMode` accepts
a mode and nothing else - so the address cannot be widened by configuration or
by accident.

The goal for the next phase is a fleet: many monitored machines, one backend.
That breaks the arrangement above, and the way it is broken determines almost
everything else - the security model, the network requirements, what has to be
provisioned at install time, and whether a machine behind NAT can be monitored
at all. It is cheap to decide now and expensive to reverse later, which is why
it is written down before anything is built.

## Decision

**The agent opens an outbound connection to the backend and posts its
snapshots.** The backend gains an authenticated ingestion endpoint. The agent
gains a credential, provisioned at install time, and keeps its loopback
listener for local reads.

The existing poller does not go away. It stays for the local agent, which is
the common case and the one that works with no configuration at all: install on
one machine, monitor that machine, configure nothing.

## Alternatives, and why they lost

### Poll N agents

The smallest change to the backend: keep the poller, give it a list of URLs
instead of one.

It loses on the first requirement. Every agent must listen on a routable
address, so every agent needs authentication, TLS, and a firewall rule - three
things the agent does not have and has twice been argued into not having. The
project would spend the sprint building an authentication system for the
component whose safety currently comes from being unreachable.

It also fails at the network level in ways that are not fixable by writing
better code. The backend must reach each agent, so a machine behind NAT cannot
be monitored, a laptop that comes and goes is unreachable whenever it is away,
and a machine that changes address has to be reconfigured centrally. Push has
none of these problems, because the connection is opened from the side that
knows it exists.

The failure modes are worse too. A polled agent that is down is
indistinguishable from one that is unreachable, and the backend is the only
place that learns either. A pushing agent that cannot reach the backend knows
so immediately, and can buffer.

### A VPN or overlay network

Put every machine on the same virtual network and keep polling. This is a real
answer and it is how a lot of infrastructure works.

It loses because it moves the requirement rather than removing it: every
monitored machine now needs a VPN client, an enrolment step, and a credential
for the overlay - all the provisioning cost of the push credential, plus a
dependency on software this project does not ship. It also leaves the agent's
unauthenticated port open to everything else on the overlay, which is a larger
blast radius than the loopback-only rule it replaces.

Worth revisiting for a deployment that already has one. Not something to
require.

### A message broker between agents and backend

Agents publish to a queue, the backend consumes. Buys durability across backend
restarts, and a natural buffer.

It loses on proportion. It is a third component to install, secure, monitor and
back up, in a product whose entire deployment story is one PowerShell script on
one Windows machine. The problem it solves - not losing snapshots while the
backend is down - is better solved by the agent retrying, because the agent
already has the data and a disk. Reconsider if ingestion volume ever justifies
it; at one snapshot per host per ten seconds, it does not.

### Keep polling, tunnel per host

SSH or WireGuard tunnels from backend to each agent, established outbound by
the agent. This is push wearing a costume: the connection is opened from the
agent's side, which is the property that mattered, but every snapshot then
travels over a general-purpose tunnel that grants far more than "post one JSON
document". Push gives the same reachability with a much smaller grant.

## Consequences

**What has to be built.**

- An authenticated ingestion endpoint on the backend. There is exactly one
  write path today - `SnapshotService._persist` into `SnapshotStore.save` - so
  this adds an HTTP route in front of code that already exists, rather than a
  new subsystem.
- A credential the agent can hold. The session mechanism is browser-shaped:
  `require_authenticated_user` reads a signed cookie, and an unattended service
  does not log in. Agents need a different credential type alongside it, not
  instead of it.
- Provisioning at install time. `Install-SysWatch.ps1` already writes
  `syswatch.env` restricted to Administrators and SYSTEM, which is where an
  agent credential belongs.
- Retry with a bounded buffer on the agent, for the interval when the backend
  is unreachable.

**What stays exactly as it is.**

- The agent's loopback listener, unauthenticated and not configurable. It is
  how the local poller reads, and widening it is what this decision exists to
  avoid.
- The poller, for the local agent.
- `SnapshotStore.save`, including its behaviour on a duplicate. `snapshots`
  carries `UniqueConstraint("host_name", "collected_at")`, and `save` returns
  `None` rather than raising when it is violated, so a retried push is already
  idempotent. That was written for a poller that polls faster than the agent
  collects; it happens to be exactly what retry needs.

**What gets harder.** The backend stops being the only thing that decides what
is stored. Today a snapshot exists because the backend went and got it; after
this, a snapshot exists because something claimed one. That is a real change in
trust, and the open questions below are its consequences.

## What this does not decide

Sprint 12's work, listed so it is not mistaken for settled:

- **Credential type and rotation.** A bearer token is the obvious choice.
  Whether it is per-agent or shared, how it is rotated, and what a compromised
  one can do, are open.
- **Host identity.** `host_name` is self-reported today - it arrives inside the
  payload as `systemInfo.hostName`. With push, a credential that can write as
  any host can also overwrite another host's history. Binding identity to the
  credential rather than to the payload is likely, but it is not decided here.
- **Transport security.** Push over plain HTTP across a network sends the
  credential in clear. TLS remains a reverse-proxy responsibility as far as
  this project is concerned, but "the agent refuses to push over plain HTTP to
  a non-loopback address" is a rule worth considering.
- **Enrolment.** How an agent gets its credential the first time, and whether
  an unknown agent is rejected or held pending approval.
- **Buffer size, and what happens when it fills.** Dropping the oldest is
  probably right for metrics; it should be a decision rather than a default.
- **Whether a pushing agent still needs its loopback listener.** It does for
  the local case. Whether a remote-only agent should skip binding at all is
  open - and skipping it would mean one fewer open port on every monitored
  machine.
