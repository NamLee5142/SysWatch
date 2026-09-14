# 0003 - What pushing cost

**Accepted**, sprint 12. A retrospective on
[0001](0001-agents-push-to-the-backend.md), superseding nothing. 0001 was
written before any of it existed; this is what happened when it was built, so
that sprint 13 can see which of its assumptions held.

## Context

0001 decided that agents push to the backend rather than being polled, and
listed five things it deliberately did not decide. Sprint 12 built it: an
ingestion endpoint, a credential, an HTTP client in C++, a buffer, a
configuration file, and an installer that provisions all of it.

The shape was right. Everything below is about the parts that were not.

## What held

Worth stating, because a retrospective that lists only mistakes is a misleading
document.

- **Push was the right direction.** Nothing during the sprint made polling look
  better in hindsight. The reachability argument - NAT, laptops, changing
  addresses - never had to be revisited.
- **`SnapshotStore.save` was already idempotent**, and 0001 predicted exactly
  why that mattered: `UniqueConstraint("host_name", "collected_at")` was written
  for a poller that outpaces collection, and it is precisely what a retried push
  needs. The ingestion endpoint answers a duplicate with `202` and
  `stored: false`, and no special handling was written for it.
- **The endpoint really was a route in front of code that already existed.**
  Phase A planned six commits and took five, one of them folded into another
  because there was less to build than the plan assumed.
- **`syswatch.env` was the right place for the credential.** It was already
  restricted to Administrators and SYSTEM for the session secret, and the agent
  already had a reason to read a file that the environment must not supply.

## What 0001 got wrong

### TLS is not a reverse proxy's problem when the client cannot speak TLS

0001 said transport security "remains a reverse-proxy responsibility as far as
this project is concerned", and offered "the agent refuses to push over plain
HTTP to a non-loopback address" as a rule worth considering.

Both sentences are individually reasonable, and together they made the sprint's
goal unreachable. A reverse proxy terminates TLS for *browsers*. It does
nothing for an agent whose hand-rolled Winsock client has no TLS in it at all:
the proxy would present a certificate the agent cannot validate, over a
protocol it cannot speak. Refusing plain HTTP off loopback while providing no
alternative means refusing to monitor a second machine, which was the point of
the sprint.

This surfaced in commit 9, where the refusal met the definition of done that
required two machines. The resolution was `allowInsecurePush`: an opt-out that
sends the credential in clear, with a written end date rather than a good
intention - [0002](0002-the-agent-speaks-tls-through-winhttp.md) settles that
the agent moves to WinHTTP, and sprint 13 commit 3 deletes the setting.

**The lesson is narrower than "we forgot TLS".** It is that "X is somebody
else's responsibility" holds only if every participant can already speak what X
provides. The agent could not, and nobody checked.

### Host identity is not one binding, it is a property of every read

0001 framed this as a single decision - bind identity to the credential rather
than to the payload - and it is the open question the sprint answered most
nearly as predicted.

What it did not anticipate is that the binding has to hold *everywhere a host
name is read*, not once at the door. The snapshot row was the obvious place and
was correct from commit 4. The alert engine was not: `AlertEngine.evaluate`
took the host from the payload, so a token for one host could raise an alert
against another machine's name while its snapshots filed correctly. That was a
second forgery hole, in code nobody had changed, found in commit 6 - which
existed because the plan scheduled confirming the alert engine still worked
rather than assuming it.

Anywhere else a host name is read from a payload is the same bug. That is a
standing property to check, not a box that got ticked.

### The token's open questions did not include the one that mattered

0001 said "a bearer token is the obvious choice" and left open whether it is
per-agent or shared, how it is rotated, and what a compromised one can do. All
three were answered without difficulty: per host, `host_name` deliberately not
unique so that a rotation can overlap, revocation as a flag rather than a
delete.

The question it did not ask is **how the token is verified, and what that costs
per request**. This sprint's own plan then got it wrong in writing, specifying
Argon2id because that is what passwords use. A password is low-entropy and
verified once at login, so 40 ms and 64 MiB is a good trade. A token is 256
random bits verified on *every push*, at an endpoint reachable before
authentication - Argon2 there is an amplification factor handed to anyone who
can send a request. It is HMAC-SHA256 under the deployment secret, with a
domain separator so that an agent token and a session token can never hash
alike.

Corrected in commit 1, before anything depended on it. The generalisable part:
choosing a credential type does not choose its verification cost, and the cost
is the part an attacker picks the frequency of.

### The argument against a broker cited a disk that is not used

0001 dismissed a message broker partly because "the agent already has the data
and a disk". The buffer that was built holds 512 snapshots **in memory**, and a
restart loses them.

The conclusion still stands - a broker remains disproportionate at one snapshot
per host per two seconds - but it stands on a weaker argument than the one
written down. Disk-backed buffering was flagged out of scope and remains a real
option; the honest reason it was not built is that nothing needed it yet, not
that the agent had a disk.

## Where 0001's open questions stand

| Question | Status |
| --- | --- |
| Credential type and rotation | **Settled.** Per host, HMAC-SHA256, revocable, rotation by overlap |
| Host identity | **Settled**, with the caveat above: it is a property to keep checking |
| Transport security | **Not settled.** `allowInsecurePush` is a stopgap; [0002](0002-the-agent-speaks-tls-through-winhttp.md) and sprint 13 finish it |
| Enrolment | **Untouched.** A token is issued by hand and pasted into the installer. Workable for tens of machines, not hundreds |
| Buffer size and overflow | **Settled.** 512, oldest dropped, in memory |
| Whether a pushing agent still needs its listener | **Untouched.** It still binds `127.0.0.1:8080` when nothing local reads it. One fewer open port per machine is still available and still unclaimed |

## One thing outside 0001's scope that changed the sprint

0001 reasoned that the backend side was low risk because the ingestion endpoint
sat in front of existing, tested code. It was right. It said nothing about the
agent side, where all the genuinely new code was, because it had no reason to.

The agent's test suite had not been running its assertions for the life of the
project. `CMAKE_BUILD_TYPE=Release` defines `NDEBUG`, which compiles `assert()`
to nothing, so all sixteen suites passed by reaching the end of `main()`. This
was found in commit 7 while building the HTTP client - the component the plan
correctly named as the sprint's biggest unknown - and was demonstrated by
breaking `Logger.cpp`'s UTC handling and watching the suite report success
while logging local time as `Z`.

The part worth recording: **the confidence that made the agent side feel safe
to extend was fictional**, and what exposed it was writing the first agent code
complicated enough to fail in an interesting way. Fixed in its own commit,
before the client was trusted.

## The estimate

Nineteen commits planned. Sprint 10 ran at 1.8x its plan and sprint 11 at 1.4x,
so sprint 12's plan called 30-40 "the honest expectation", naming commit 7 as
the first risk to that number.

It landed at 21: nineteen planned, one folded into another, and three added -
the `NDEBUG` fix, an alert-flapping bug found by a mid-sprint audit, and
[0002](0002-the-agent-speaks-tls-through-winhttp.md).

The hedge was wrong, in the more useful direction. Commit 7 *was* the hardest
work and it *did* uncover the worst problem, and it was still one commit: the
unknowns were real and stayed inside the commits that owned them. A plan whose
risky commits are correctly identified appears to cost less than one whose risk
is spread evenly - even when the risks land.

## Consequences

- Sprint 13 starts from [0002](0002-the-agent-speaks-tls-through-winhttp.md)
  and removes `allowInsecurePush`. Until it does, a multi-machine deployment
  needs a network somebody is willing to send a credential across, and
  `deployment.md` says so plainly.
- Enrolment, and the remote agent's unnecessary listener, are unclaimed. They
  should be planned rather than rediscovered.
- "Host identity comes from the credential" is a rule to re-check at every new
  read of a host name, not a completed task.
