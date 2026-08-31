# Sprint 7 — Process & Network Monitoring

**Goal:** take SysWatch past CPU / memory / disk by adding **process** and
**network** collectors to the C++ agent, flowing the new metrics through the
snapshot pipeline unchanged in shape, and giving them their own dashboard pages.

```text
   Windows APIs
        │
        ▼
   C++ collectors          ← the only place the OS is queried
        │
        ▼
     Snapshot
        │
        ▼
   HTTP /snapshot
        │
        ▼
     FastAPI
        │
        ▼
  React dashboard
```

The load-bearing principle: **the agent is the only component that touches the
operating system.** The backend must not grow a `psutil` dependency or shell out
to `tasklist`; if the dashboard needs a number, the agent collects it, the
snapshot carries it, and the backend passes it through. Every existing metric
already obeys this — the two new ones do too.

## Starting point

The snapshot pipeline works end to end and is the template to follow, not
rebuild. What is missing is entirely additive, but five existing assumptions
narrow at the point of contact:

1. **The JSON serializer cannot emit an array.** `snapshotToJson()` in
   `HTTPServer.cpp` is a hand-rolled emitter with `jsonFor()` overloads per
   domain type, all of which produce objects. A process list and an interface
   list both need `[ … ]`, which nothing in the agent writes yet.
2. **The stored schema is one flat row per snapshot.** `SnapshotRecord` has a
   column per scalar (`cpu_usage_percent`, `mem_used_mb`, …). A variable-length
   list of processes or interfaces has nowhere to live in that shape.
3. **`/snapshots/series` hardcodes a 0–100 axis.** `metric_expression()` returns
   every metric as a percentage on purpose, and `SeriesPoint.value` and the
   dashboard's `MetricChart` both depend on it — fixed `domain={[0, 100]}`,
   `%`-suffixed ticks. Process count and bytes/sec are neither percentages nor
   the same axis as each other.
4. **`Metric` is `Literal["cpu", "memory", "disk"]`.** Adding chartable metrics
   means widening that type and the `metric_expression` switch behind it.
5. **New `Snapshot` fields break an un-upgraded agent.** Sprint 5 hit this with
   `collectedAt` and solved it by shipping the field `Optional` for one release.
   The same rule applies here or the backend 502s every payload from an agent
   that has not been rebuilt.

## Locked decisions

| Decision | Final choice | Rationale |
| --- | --- | --- |
| Where the data is collected | **Agent only** | The architectural principle above. Python never calls a Windows API. |
| Cross-platform | **Windows implementation now, behind the existing `#ifdef _WIN32` seam** | Same as `CPUCollector` / `MemoryCollector` today: real on Windows, empty list / zero elsewhere. Linux and macOS follow when the agent's platform layer does. |
| Process ranking | **Top 10 by memory working set** | A stateless `GetProcessMemoryInfo` call per PID. Per-process CPU% needs `GetProcessTimes` deltas keyed by a recycling PID set — real state, real bookkeeping, and out of scope for v1 (flagged below). Ships an honest number rather than a faked one, the Sprint 5 way. |
| Process count | **Full count from the toolhelp walk, independent of the top list** | `OpenProcess` fails on protected processes; the count must not drop just because the agent could not inspect one. |
| Network rate | **Per-second rate derived in the collector, plus cumulative counters** | Reuses the exact delta pattern `CPUCollector` established — previous sample on the instance, first reading `0`, a 100 ms floor. Cumulative octets travel too, so a missed poll does not lose data. |
| Interface filter | **Operational, non-loopback interfaces only** | `IfOperStatusUp`, skip `IF_TYPE_SOFTWARE_LOOPBACK`. A list of down VPN adapters is noise. |
| Storage shape | **Aggregates as columns, detail as JSON** | `process_count`, `net_bytes_sent_per_sec`, `net_bytes_recv_per_sec` become first-class nullable columns so `/snapshots/series` can bucket them. The top-processes list and per-interface breakdown go in `process_top` / `network_interfaces` JSON columns — point-in-time detail, read only from `latest`, never charted historically. |
| No child tables | **Keep the single `snapshots` table** | Consistent with Sprint 5's "avoid premature normalization". Nothing queries a process relationally; a `snapshot_processes` table would buy nothing and cost a join. |
| Series axis | **Drop the 0–100-only contract; add `unit` to `Series`** | `percent` \| `count` \| `bytes_per_sec`. The unit travels with the data so one chart component can still render any metric, it just stops assuming the range. |
| Back-compat | **`processInfo` / `networkInfo` `Optional` for one release** | The `collectedAt` precedent. |
| Dashboard chart | **Two single-line charts for network (sent, recv)** | `MetricChart` gains unit-awareness but not multi-series. A combined dual-line chart is a nice-to-have, not this sprint. |

## Schema

`SnapshotRecord` gains six nullable columns — nullable because existing rows and
un-upgraded agents will not have them:

| Column | Type | Notes |
| --- | --- | --- |
| `process_count` | integer, null | Total running processes; bucketable by `/snapshots/series` |
| `net_bytes_sent_per_sec` | float, null | Summed across interfaces; bucketable |
| `net_bytes_recv_per_sec` | float, null | Summed across interfaces; bucketable |
| `process_top` | JSON, null | `[{pid, name, memoryMB}]`, at most 10 — detail, read from `latest` only |
| `network_interfaces` | JSON, null | `[{name, bytesSent, bytesRecv, bytesSentPerSec, bytesRecvPerSec}]` — detail, read from `latest` only |

One Alembic revision, batch mode, named per the metadata convention as before.
No new index or constraint: none of these columns are filtered on.

Agent-side, `Snapshot` gains `processInfo` and `networkInfo`, mirroring the
nesting of `cpuInfo` and friends:

```text
processInfo : { count, top: [ { pid, name, memoryMB } ] }
networkInfo : { interfaces: [ { name, bytesSent, bytesRecv,
                                bytesSentPerSec, bytesRecvPerSec } ] }
```

---

## Commit plan

### Phase A — Agent: process collector

**1. `feat(agent): add ProcessInfo domain type`**
`agent/include/domain/ProcessInfo.h`: `ProcessEntry { unsigned long pid;
std::string name; unsigned long long memoryMB; }` and the aggregate
`ProcessInfo { int count; std::vector<ProcessEntry> top; }`. Matches how
`CPUInfo` / `MemoryInfo` are laid out.

**2. `feat(agent): add ProcessCollector`**
`CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS)` plus `Process32NextW` for the
count and the names; `OpenProcess` + `GetProcessMemoryInfo` for each entry's
working set; sort descending by memory and keep the first 10. Windows-only
behind `#ifdef _WIN32`, empty on other platforms.
*Watch out:* `OpenProcess` returns `NULL` for protected and system processes —
skip that entry, never abort the walk. The count comes from the toolhelp
iteration, not from how many handles opened.
*Done when:* a debug print of `collect()` tracks Task Manager's process count.

**3. `feat(agent): collect process info in SnapshotCollector`**
Add a `ProcessCollector` member and `snapshot.processInfo =
processCollector.collect();`. `SnapshotCollector::collect()` is already
non-const, so no signature change.

**4. `test(agent): cover ProcessCollector`**
New `agent/tests/process_collector_tests.cpp`, wired into CMake beside
`cpu_collector_tests`. Count is `> 0` on any real machine; `top` holds at most
10 entries, sorted by `memoryMB` descending; every `name` is non-empty.

### Phase B — Agent: network collector

**5. `feat(agent): add NetworkInfo domain type`**
`agent/include/domain/NetworkInfo.h`: `NetworkInterfaceInfo { std::string name;
std::uint64_t bytesSent; std::uint64_t bytesRecv; double bytesSentPerSec; double
bytesRecvPerSec; }` and `NetworkInfo { std::vector<NetworkInterfaceInfo>
interfaces; }`.

**6. `feat(agent): add NetworkCollector with per-interface rate sampling`**
`GetIfTable2` (iphlpapi) for cumulative in/out octet counters per interface.
Keep the previous counters and a timestamp per interface **keyed by LUID** on
the collector instance, and derive `bytesSentPerSec` / `bytesRecvPerSec` from
the delta — first reading `0`, a 100 ms floor, exactly as `CPUCollector` does.
Filter to `IfOperStatusUp`, skip `IF_TYPE_SOFTWARE_LOOPBACK`.
*Watch out:* interfaces come and go (VPN, USB NIC). Drop LUIDs not seen this
tick, or a re-appearing adapter computes a rate against a stale counter and
reports a multi-gigabyte spike. Also confirm `Agent` holds one long-lived
collector — the rate state is on the instance, and a fresh collector per cycle
would make every reading a first sample. (`CPUCollector` already relies on this;
Sprint 6 verified it.)

**7. `feat(agent): collect network info in SnapshotCollector`**
Add the `NetworkCollector` member and `snapshot.networkInfo =
networkCollector.collect();`.

**8. `test(agent): cover NetworkCollector`**
At least one interface on a connected machine; first-sample rates are exactly
`0`; a burst of calls inside the 100 ms floor repeats the last rates unchanged;
cumulative counters are non-decreasing across samples; every rate is
non-negative.

### Phase C — Snapshot & API evolution

**9. `feat(agent): serialize process and network info in snapshot JSON`**
Extend `snapshotToJson()`: add a `jsonArray()` helper — the emitter has no array
support today — and `jsonFor()` overloads for `ProcessInfo`, `ProcessEntry`,
`NetworkInfo`, `NetworkInterfaceInfo`. Output gains
`"processInfo":{"count":213,"top":[…]}` and
`"networkInfo":{"interfaces":[…]}`.
*Done when:* `http_server_snapshot_tests` asserts both blocks are present and
parse.

**10. `feat(backend): add process and network fields to the Snapshot model`**
Pydantic `ProcessEntry`, `ProcessInfo`, `NetworkInterface`, `NetworkInfo`; add
`processInfo` and `networkInfo` to `Snapshot`.
*Compatibility:* both `Optional` with a `None` default for one release, the way
`collectedAt` shipped in Sprint 5 — otherwise every payload from an un-rebuilt
agent fails validation and the backend answers 502.

**11. `feat(backend): store process count and network throughput`**
`SnapshotRecord` gains `process_count`, `net_bytes_sent_per_sec`,
`net_bytes_recv_per_sec`, and the `process_top` / `network_interfaces` JSON
columns, all nullable. `SnapshotStore._to_record()` writes them (summing the
per-interface rates for the two throughput columns); `Snapshot.from_record()`
rebuilds the nested `processInfo` / `networkInfo` shape from the row.
*Watch out:* `from_record()` must tolerate a row where every new column is
`NULL` — that is every row written before this sprint.

**12. `feat(backend): add the alembic migration for the new columns`**
Autogenerated revision. `alembic upgrade head` against a populated database
leaves existing rows with `NULL`s and does not rewrite them; `alembic check` is
clean afterwards.

**13. `feat(backend): extend /snapshots/series with process and network metrics`**
`Metric` gains `processes`, `net_sent`, `net_recv`; `metric_expression()`
returns the raw column for each (no percentage wrapping). `Series` gains a
`unit` field — `"percent" | "count" | "bytes_per_sec"`.
*Watch out:* this ends the "every series is 0–100" invariant. Update the
`SeriesPoint.value` docstring and the `metric_expression` docstring that both
assert it, and make sure the `NULL`-average drop in `series()` still reads
correctly for a count (a bucket with no rows, not "a zero total").

**14. `feat(backend): carry the process and network blocks through the read APIs`**
`SnapshotService` passes the new nested fields straight through from the agent
payload; `/snapshot`, `/snapshots` items and `/snapshots/latest` all include
them (live from the agent, or rebuilt by `from_record()` from storage).

### Phase D — Dashboard

**15. `feat(dashboard): mirror the process and network API types`**
`api/types.ts` gains `ProcessEntry`, `ProcessInfo`, `NetworkInterface`,
`NetworkInfo`, the widened `Metric` union, and `Series.unit`; `Snapshot` gains
the two optional blocks.

**16. `feat(dashboard): add a bytes-per-second formatter`**
`lib/format.ts` `formatBytesPerSec()` — `B/s → KB/s → MB/s → GB/s` — beside the
existing MB→GB memory/disk helper, with the same rounding rules.

**17. `feat(dashboard): make MetricChart unit-aware`**
Accept a `unit` prop. `percent` keeps the fixed `[0, 100]` axis and `%` ticks;
`count` and `bytes_per_sec` get an auto domain and a unit-formatted tick and
tooltip. Default stays `percent`, so the CPU / Memory / Disk callers do not
change.

**18. `feat(dashboard): add the Process page and route`**
A process-count `StatCard`, a count trend `MetricChart`
(`/snapshots/series?metric=processes`), and a top-processes table (name, PID,
memory) from `/snapshots/latest`. Nav item between Disk and System.

**19. `feat(dashboard): add the Network page and route`**
One card per interface (name, receive rate, send rate) from
`/snapshots/latest`, plus receive and send trend charts from
`/snapshots/series?metric=net_recv` and `metric=net_sent`. Nav item after
Process.

**20. `feat(dashboard): show process and network tiles on Overview`**
A process-count tile and a total-throughput tile added to the Overview grid,
holding the "no scrolling on a laptop" constraint Sprint 6 set for that page.

### Phase E — Testing & quality

**21. `test(agent): cover process and network JSON serialization`**
The `jsonArray()` helper emits valid JSON for an empty and a populated list; a
full snapshot with both blocks round-trips through the request parser.

**22. `test(backend): cover the new model fields and back-compat`**
A payload with no `processInfo` / `networkInfo` still validates (the `Optional`
guarantee); a full payload round-trips; `Snapshot.from_record()` handles both a
populated row and an all-`NULL` legacy row.

**23. `test(backend): cover storage and series for the new metrics`**
`SnapshotStore` round-trips the columns and the JSON detail; `series("processes")`
averages the count; `series("net_recv")` returns `unit == "bytes_per_sec"`; the
empty-range and over-`MAX_POINTS` behaviours are unchanged.

**24. `test(backend): extend the integration pass with process and network data`**
`tests/test_snapshot_integration.py` feeds a stubbed agent payload carrying both
blocks and asserts they survive to `/snapshots/latest` and `/snapshots/series`.

**25. `test(dashboard): cover the new pages, formatter and chart`**
`formatBytesPerSec()` boundaries; `MetricChart` renders a non-percent axis;
Process and Network pages render loading / error / success from mocked
responses.

**26. `docs(agent): record the real-agent verification pass`**
Run the built agent, `curl /snapshot`, confirm `processInfo.count` tracks Task
Manager and the `networkInfo` rates move under a download. Capture the observed
shape in the agent README's "Observed behaviour" table, as Sprints 5 and 6 did.

### Phase F — Documentation

**27. `docs: document process and network monitoring`**
Agent README — the two collectors, the domain types, the JSON shape. Backend
README — the expanded `/snapshot` and `/snapshots` payload, the new
`/snapshots/series` metrics and the `unit` field, the new columns and the
migration. Dashboard README — the Process and Network pages. Root README — tick
Phase 1 *Network collector*, add process monitoring to the metric list, and
refresh the architecture diagram for the nested shape.

---

## Out of scope, flagged

- **Per-process CPU%.** Needs `GetProcessTimes` deltas keyed by a PID set that
  churns and recycles between samples — real state for a v1 that ships a
  memory-ranked list instead. A natural follow-up once the collector exists.
- **Per-process disk or network I/O attribution.** `GetProcessIoCounters` is a
  separate effort; the sprint reports totals, not who caused them.
- **Historical charting of the top-processes list or the per-interface
  breakdown.** Those are latest-only JSON detail. Only `process_count` and the
  summed throughput are bucketed into `/snapshots/series`.
- **Managing processes from the dashboard** (kill, priority). Read-only;
  anything that acts on a remote machine is Phase 4 with authentication in front
  of it.
- **The network connection table** — listening ports, per-connection state,
  netstat-style data. A different collector.
- **A combined sent/recv dual-line chart.** Two charts this sprint.
- **Linux / macOS implementations** of both collectors. Windows-first behind the
  existing platform seam, empty elsewhere — the same position `CPUCollector` is
  in today.
- **Alerting on a process count or a bandwidth threshold.** Phase 4, with the
  rest of the alert engine.
