# SysWatch Agent

Native C++ monitoring agent. Collects hardware and OS metrics on a fixed
interval and serves the most recent reading over HTTP for the
[backend](../backend/README.md) to poll.

```text
Windows APIs  ->  collectors  ->  Snapshot  ->  GET /snapshot  ->  backend
```

The agent is the only component that touches the operating system. Every number
the backend and dashboard show originates in a collector here.

## Requirements

- A C++17 compiler. Verified with MinGW-w64 (`C:/mingw64`) and Ninja.
- CMake 3.15 or newer.
- Windows: the collectors are implemented against the Win32 API. On other
  platforms they compile but return empty readings.

## Building

```bash
cd agent
cmake -S . -B build -G Ninja
cmake --build build
```

`agent_core` is a static library holding the collectors, the scheduler and the
HTTP server; `agent.exe` is a thin entry point over it. Each test is its own
executable linked against `agent_core`.

## Running

```bash
PATH="/c/mingw64/bin:$PATH" ./build/agent.exe     # Git Bash
```

Listens on `127.0.0.1:8080`, collects every 2 seconds, and serves `/snapshot`
until it receives `SIGINT` (Ctrl+C) or `SIGTERM`.

`agent.exe` is **statically linked** (`-static-libgcc -static-libstdc++
-static`), so it imports no MinGW runtime DLL and needs nothing on `PATH`:

```text
ADVAPI32.dll  IPHLPAPI.DLL  KERNEL32.dll  WS2_32.dll  msvcrt.dll
```

That is not a preference. It once linked `libstdc++-6.dll`, `libgcc_s_seh-1.dll`
and `libwinpthread-1.dll` dynamically, which was survivable in a shell with the
toolchain on `PATH` and fatal as a service: LocalSystem inherits no such `PATH`,
so the process exited 127 with no message anywhere - registered, started, and
dead. CI checks the import table on every build for exactly this reason.

## Running as a service

The same binary. `--service` makes it dispatch to the Service Control Manager
instead of running in the console, and the SCM passes that argument itself.

```text
agent.exe --install      register SysWatchAgent, starting at boot
agent.exe --uninstall    stop and remove it
agent.exe --service      run under the SCM. Started by the SCM, not by hand
agent.exe --help         the list above
```

`--install` and `--uninstall` need an administrator prompt. Console mode stays
the default, so development does not need a service install per rebuild.

Installed, it runs as **LocalSystem**, starts automatically at boot, and is
configured to restart on failure after 5 s, then 10 s, then 60 s, with the
count resetting after a day. Kill the process and the SCM brings it back.

```text
sc.exe queryex SysWatchAgent      state and PID
sc.exe qc SysWatchAgent           binary path, start type, account
sc.exe qfailure SysWatchAgent     recovery actions
```

With no console to write to, a service has to leave evidence somewhere: it logs
to `%PROGRAMDATA%\SysWatch\logs\agent.log`, rotating at 2 MB with three kept,
appending across restarts so the line before a restart survives.

```text
2026-09-04T10:19:23.034Z INFO agent: Agent starting, version 0.10.0
2026-09-04T10:19:23.036Z INFO agent: Listening on 127.0.0.1:8080
2026-09-04T10:19:23.036Z INFO agent: Collecting every 2000ms
```

Times are UTC, in the same ISO 8601 shape the API serves `collectedAt` in, so a
log line and the snapshot it describes can be compared without arithmetic.

The version comes from the repository's `VERSION` file, read by CMake at
configure time, so a log from a machine in the field names the build that wrote
it. [docs/deployment.md](../docs/deployment.md) covers installing the whole
system rather than the agent alone.

## Network exposure

**The agent binds `127.0.0.1` and only `127.0.0.1`. This is not configurable,
and must not become configurable.**

`GET /snapshot` is unauthenticated and returns the machine's CPU, memory, disk,
running-process and per-interface network detail to anyone who asks. SysWatch
does not authenticate here — it authenticates at the
[backend](../backend/README.md) boundary, on the assumption that the only thing
able to open a socket to this port is the backend process on the same host.
Binding `INADDR_ANY` would publish all of that to the local network and route
straight past the backend's login.

Consequences, deliberately:

- `AgentConfig` has a `serverPort` but no bind host.
- The dashboard never talks to the agent; it only ever calls the backend.
- The port must not be forwarded, published from a container, or opened in a
  firewall. Remote collection is a multi-host agent-registration problem with
  its own credential design — not a bind-address change.

`tests/http_server_bind_tests.cpp` enforces this: it finds the host's own
non-loopback addresses and fails if any of them can reach the server.

## Testing

Each `*_tests` target is a standalone assert-based program that exits non-zero
on failure. Run them from `build/` with the toolchain on `PATH`:

```bash
cd build
for t in *_tests.exe; do ./"$t" || echo "FAILED: $t"; done
```

The collector tests read the real machine, so they assert ranges and invariants
(a non-zero process count, rates that are finite and non-negative, a top list
bounded at ten and sorted) rather than exact values.

## Collectors

| Collector | Reads | Via |
| --- | --- | --- |
| `CPUCollector` | core count, usage % | `GetSystemTimes` delta between samples |
| `MemoryCollector` | total / used MB | `GlobalMemoryStatusEx` |
| `DiskCollector` | total / free GB of `C:\` | `GetDiskFreeSpaceExA` |
| `OsCollector` | OS name, version, host name | `RtlGetVersion`, `GetComputerNameA` |
| `ProcessCollector` | process count, top 10 by memory | `CreateToolhelp32Snapshot`, `GetProcessMemoryInfo` |
| `NetworkCollector` | per-interface bytes and per-second rates | `GetIfTable2` |

`CPUCollector` and `NetworkCollector` are **stateful** — a rate is a delta
between successive samples, so each keeps its previous reading and a 100 ms
minimum interval below which the last value stands. `SnapshotCollector` owns one
long-lived instance of each; constructing a fresh collector per cycle would make
every reading a first sample.

`ProcessCollector` ranks by memory working set, not CPU: working set is one
stateless read per process, whereas per-process CPU would need `GetProcessTimes`
deltas tracked across a PID set that recycles between samples. A process the
agent cannot open still counts; only its memory reads as zero.

`NetworkCollector` filters to operational hardware interfaces. `GetIfTable2`
returns a row per filter layer stacked on each adapter, so an unfiltered walk
would count "Wi-Fi" five or six times over.

## Snapshot shape

`GET /snapshot` returns `200` with the current reading, or `204` before the
first collection.

```json
{
  "collectedAt": "2026-08-12T11:15:27Z",
  "cpuInfo": {"coreCount": 20, "usagePercent": 7.4},
  "memoryInfo": {"totalMB": 16124, "usedMB": 11945},
  "diskInfo": {"totalGB": 475, "freeGB": 36},
  "systemInfo": {"name": "Microsoft Windows", "version": "10.0.26200", "hostName": "devbox"},
  "processInfo": {
    "count": 411,
    "top": [{"pid": 15888, "name": "Code.exe", "memoryMB": 442}]
  },
  "networkInfo": {
    "interfaces": [
      {"name": "Wi-Fi", "bytesSent": 188659916, "bytesRecv": 3386875336,
       "bytesSentPerSec": 3108.1, "bytesRecvPerSec": 2009.1}
    ]
  }
}
```

The JSON is written by a hand-rolled emitter in `HTTPServer.cpp` — one
`jsonFor()` overload per domain type, plus a `jsonArray()` template for the
`top` and `interfaces` lists.

## Configuration

`AgentConfig` (collection interval, server port, log path) is currently
constructed in `main.cpp`. A file-based configuration loader is the open Phase 1
item.

There is no bind-host setting and a configuration loader must not add one — see
[Network exposure](#network-exposure).

## Structure

```text
agent/
    include/
        collector/   # One header per collector, plus SnapshotCollector
        domain/      # Plain data types: CPUInfo, ProcessInfo, NetworkInfo, ...
        http/        # HTTPServer, request parser
        scheduler/   # Fixed-interval worker thread
    src/             # Matching implementations
    tests/           # One assert-based program per target
```
