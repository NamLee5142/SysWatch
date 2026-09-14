# 0002 - The agent speaks TLS, through WinHTTP

**Accepted**, sprint 12, to be implemented as sprint 13's opening move. Nothing
in sprint 12 implements it; the point is that the argument is settled before the
sprint that has to act on it, and that `allowInsecurePush` is understood as a
stopgap with an end date rather than a setting.

## Context

[0001](0001-agents-push-to-the-backend.md) settled that agents push. Sprint 12
built that, and its commit 9 then had to answer a question 0001 left open: what
stops the credential crossing the network in clear?

The answer it could give was "nothing". The agent's HTTP client is hand-rolled
on Winsock and speaks no TLS, so `https://` is refused at startup and remote
`http://` is refused unless `allowInsecurePush` is set - which sends the token
in an `Authorization` header readable by anything on the path, and warns on
every start that it is doing so.

That left sprint 12's own definition of done in tension with itself: two
machines can only report to one backend on a network somebody has decided to
trust. The flag is honest about it, and it is not somewhere to stay.

## Decision

**The agent makes its outbound requests through WinHTTP**, the Windows HTTP
client, and `https://` becomes the supported way to reach a backend on another
machine. `allowInsecurePush` is removed in the same sprint that makes it
unnecessary.

WinHTTP validates the certificate chain against the machine's own trust store.
No certificate parsing, no trust store to build, no crypto to maintain.

## Alternatives, and why they lost

### Sign each request with the token instead of sending it

An HMAC over the body, a timestamp and the path, with the token as the key. The
credential never crosses the wire, and replay is already harmless here because
`snapshots` is unique on `(host_name, collected_at)` - a replayed push is a
duplicate.

It loses on what it does not cover, which is most of what is at risk. A push
carries the hostname, the OS version, CPU, memory and disk figures, **the top
ten process names and their PIDs**, and every network interface with its
throughput. On one machine that is your own data on your own loopback. Across a
fleet it is a map of the estate - what software runs where, which machines are
loaded, which are idle. That is the bulk of the payload and signing leaves all
of it readable.

It also authenticates nobody. An attacker who can redirect traffic cannot forge
a snapshot, but can receive every snapshot the fleet produces and drop it -
monitoring stops while every agent reports success.

And it means writing SHA-256 and HMAC in C++, because the agent has no crypto
library. Hand-rolled crypto to avoid using the platform's TLS is the wrong way
round.

### Schannel directly

The Windows TLS API that WinHTTP is built on. Correct, and roughly a sprint on
its own: handshake, certificate chain validation, revocation, renegotiation,
and error reporting an operator can act on. WinHTTP is that work, already done,
maintained by the platform vendor, and patched by Windows Update.

### OpenSSL, or any bundled TLS library

Adds a dependency to a project whose agent is one static binary with no runtime
requirements - a property `release.yml` has a check for. It also moves
certificate trust into the application, so the agent would carry its own CA
bundle and go stale.

### A TLS-terminating sidecar on each monitored machine

stunnel or similar, listening on loopback and forwarding outward. Keeps the
agent unchanged, and is a second thing to install, configure, secure, monitor
and explain on every machine - to avoid linking one system library.

### WinINet

The other Windows HTTP API, and the wrong one: Microsoft documents it as
unsupported from a service or any non-interactive context. The agent runs as
LocalSystem under the Service Control Manager, which is exactly that context.

## Consequences

**What this retires.** Most of sprint 12's commit 7. WinHTTP replaces the
hand-rolled client: connect with a deadline, request framing, response parsing,
`Content-Length` handling, the chunked refusal. `HttpClient` and its parsing
tests go with it.

That work is not wasted - it is what found that Winsock reports a failed connect
in `select`'s exception set, and the agent's *server* is still Winsock and stays
- but hand-rolled HTTP parsing that Windows does correctly is a liability to
carry, not an asset to keep. One transport, not two: WinHTTP speaks plain HTTP
to loopback as well, so the local case uses the same path.

**What this cements.** The agent becomes explicitly Windows-only. It already is
- every collector is `#if defined(_WIN32)` with a stub returning zero - and
Phase 1's cross-platform layer stays unticked either way. Worth saying out loud
rather than discovering later.

**What gets better beyond the token.** Certificate validation means the agent
knows it is talking to the intended backend, which signing could never provide.

**What stays a reverse proxy's job.** Terminating TLS in front of the backend.
The backend still serves plain HTTP and still binds loopback by default; this
decision is about what the *agent* will speak to whatever is in front of it.

## What this does not decide

- **Certificate pinning**, and whether a deployment with a private CA needs
  anything beyond installing that CA in the machine's trust store.
- **Self-signed certificates.** Refusing them is the safe default and will
  annoy somebody on a lab network; whether there is an opt-out, and how loud it
  is, is sprint 13's to settle. The lesson from `allowInsecurePush` is that such
  a flag needs an end date when it is introduced.
- **Whether the backend should refuse plain HTTP from a non-loopback agent**,
  which is the same rule enforced from the other end.
- **Proxy support.** WinHTTP can discover a system proxy; whether the agent
  should use one is a question about the environments this runs in.
