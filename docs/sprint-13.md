# Sprint 13 — Reaching another machine safely

**Opened early, and deliberately incomplete.** Sprint 12 is still running. This
file exists because sprint 12 shipped a setting with a warning on it -
`allowInsecurePush` - and a stopgap without a written end date is a stopgap that
becomes permanent. Phase A below is settled; everything after it is planned when
sprint 12 closes and its own retrospective is written.

---

## The one thing already decided

Sprint 12 made agents push, and then had to answer what protects the credential
on the way. The answer was: nothing. The agent's HTTP client is hand-rolled on
Winsock and speaks no TLS, so an operator monitoring a second machine has to set
`allowInsecurePush` and accept that the token crosses the network in clear on
every push.

That is recorded in full in
[decisions/0002-the-agent-speaks-tls-through-winhttp.md](decisions/0002-the-agent-speaks-tls-through-winhttp.md),
including the four alternatives and why each lost. The short version: **the
agent will make its outbound requests through WinHTTP**, which is the Windows
HTTP client, validates certificates against the machine's own trust store, and
is supported from a service - which WinINet is not, and the agent runs as
LocalSystem.

The credential is not the whole reason. A push carries the top ten process
names and PIDs, every network interface and its throughput, and the machine's
OS version. Across a fleet that is a map of the estate, it is the bulk of the
payload, and it is exactly what request signing would have left readable.

---

## Carried over from sprint 12

**Verify pushing between two real machines, before commit 2.**

Sprint 12's definition of done ended with "verified between two real machines,
not two processes on one", and closed without it. Every link in the chain is
tested - CI installs a pushing agent and asserts a snapshot arrives under the
token's host - but always on one machine, so the network between two has never
been in the path: DNS, a firewall, a backend that is not on loopback, latency
that is not microseconds.

**Why before commit 2 specifically.** Commit 2 moves the push to `https://`.
If the first two-machine run happens after that, a failure has two candidate
causes - the network or the TLS - and nothing to tell them apart. Run on plain
HTTP first, and TLS becomes the only new variable when it arrives.

This is a test, not a commit. Whatever it finds is the commit - the way sprint
12's commit 12 was named for what pushing to a real backend turned up.

### Procedure

On a trusted network only: steps 1 and 2 put the backend and its session
cookies on that network in clear, and step 6 undoes it.

1. **Make the backend reachable** from the second machine. In its
   `syswatch.env`, set `SYSWATCH_HOST=0.0.0.0` and restart `SysWatchBackend`.
2. **Open the port to the second machine only**, from an elevated prompt on
   the backend machine:

   ```text
   New-NetFirewallRule -DisplayName "SysWatch test" -Direction Inbound `
       -Protocol TCP -LocalPort 8000 -RemoteAddress <second-machine-ip> -Action Allow
   ```

   A rule scoped to one address, because the point is to test pushing, not to
   put the backend on the whole network.
3. **Issue a token** on the backend machine, deliberately naming a host that is
   *not* the second machine's Windows hostname:

   ```text
   python -m app.auth.create_agent_token --host twin-test
   ```

4. **Install on the second machine** with it, following
   [deployment.md](deployment.md#monitoring-a-second-machine):

   ```text
   powershell -ExecutionPolicy Bypass -File deploy\Install-SysWatch.ps1 `
       -BackendUrl http://<backend-ip>:8000/api/ingest/snapshot `
       -AgentToken <token> -AllowInsecurePush -SkipAdminAccount
   ```

5. **Run the checks below.**
6. **Undo steps 1 and 2** - remove `SYSWATCH_HOST` and delete the firewall rule
   (`Remove-NetFirewallRule -DisplayName "SysWatch test"`) - unless the machine
   is staying on that network behind something that gives it TLS.

### What counts as passing

Each of these has been checked on one machine. None has been checked across a
network.

| | Check | What it proves on a real network |
| --- | --- | --- |
| 1 | `twin-test` appears in the backend machine's host selector | The whole chain, end to end |
| 2 | `create_agent_token --list` shows a last-seen time, not `never` | The token authenticated across the network |
| 3 | Snapshots are filed under `twin-test`, the second machine's real hostname is not in the host selector, and the backend's `syswatch.log` says once that `'twin-test'` reported a different hostname | Identity comes from the credential, not the payload - and the mismatch is noticed, once, rather than every push |
| 4 | Stop `SysWatchBackend` for two minutes, start it again: the gap fills in | The buffer holds and drains after a real outage |
| 5 | Shut the second machine down: its page shows the stale banner within four minutes | Staleness is reported for a host that pushes. Three minutes is the threshold; the banner re-checks once a minute, so up to four |
| 6 | Re-run the installer on the second machine with no push parameters: it keeps reporting | Upgrade preserves the push configuration |

If a check fails, the second machine's
`C:\ProgramData\SysWatch\logs\agent.log` names the reason - the table in
[deployment.md](deployment.md#3-check-it-arrived) maps each line to a cause.

*Done when:* all six pass, and sprint 12's definition of done is updated to say
so - or a check fails, and the fix is the commit that closes it.

---

## Phase A — TLS (commits 1–5)

**1. `feat: an http client built on winhttp`**
`WinHttpOpen`/`Connect`/`OpenRequest`/`SendRequest`/`ReceiveResponse`, behind
the same result type the current client returns, so the pusher does not care
which is underneath. Links `-lwinhttp`, a system library; no new dependency, and
the static-link check in `release.yml` still has to pass.
*Watch out:* WinHTTP is wide-character throughout, and the URL, headers and
token all arrive as `std::string`. The conversion is where a token gets
mangled, and a mangled token is a 401 that looks like a revoked one.
*Done when:* it round-trips against the agent's own server, and against a real
backend over both `http://` to loopback and `https://` to a certificate.

**2. `feat: push over https`**
Remove the startup refusal of `https://`. Certificate validation is WinHTTP's
default and stays on.
*Done when:* an agent pushes to an `https://` backend and refuses one whose
certificate does not validate, with a message naming which.

**3. `feat: remove allowInsecurePush`**
The setting, its warning, and the branch that honoured it. A configuration that
still sets it is refused at startup with a message pointing at `https://` -
silently ignoring it would leave an operator believing they had opted into
something.
*Watch out:* this is the commit that breaks an existing install. It needs a
line in the release notes, not just a commit message.
*Done when:* there is no way to send a token over plain HTTP to another machine,
and a config that tries says so.

**4. `chore: retire the winsock client`**
`HttpClient`, `http_client_tests`, `http_client_parsing_tests`. One transport,
not two. The agent's *server* stays on Winsock and is untouched.
*Watch out:* `Url` stays - the loopback check in it is still what decides
whether plain HTTP is acceptable at all.
*Done when:* the agent has exactly one way of making an outbound request.

**5. `docs: how to give the backend a certificate`**
`deployment.md` gains it: a reverse proxy in front, what the agent needs in the
machine's trust store, and what a private CA costs.
*Done when:* installing a pushing agent against a TLS backend needs no reading
of source.

---

## Then

To be planned when sprint 12 closes. The candidates already visible:

- **A self-signed opt-out**, if one is wanted at all - and if so, with an end
  date written into the commit that adds it. That is the lesson from
  `allowInsecurePush`: a flag introduced without one is a flag that stays.
- **The backend refusing plain HTTP ingestion from a non-loopback agent** - the
  same rule from the other end, which does not depend on every agent being
  correctly configured.
- **Whatever sprint 12's retrospective turns up.** Sprint 11 found `strftime`
  and a timezone bug that only appeared off UTC; sprint 12 found that every
  agent assertion had been compiled out for the life of the project. Neither was
  predictable, and both were worth more than what was planned.

---

## Out of scope, already

- **Certificate pinning.** The machine's trust store is the answer until
  somebody has a reason it is not.
- **Mutual TLS.** A client certificate per agent is a second credential to
  provision and revoke alongside the token, for a property the token already
  provides.
- **TLS on the agent's own listener.** It binds `127.0.0.1` and always will;
  encrypting a loopback socket protects nothing that is not already protected by
  the socket being loopback.
- **Terminating TLS inside the backend.** Still a reverse proxy's job. This
  sprint is about what the agent speaks to whatever is in front of it.
