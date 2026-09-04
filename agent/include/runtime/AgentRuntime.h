#pragma once

#include <functional>
#include "agent/Agent.h"
#include "config/AgentConfig.h"

namespace runtime {

// Optional hooks. Both default to doing nothing, which is what the service
// wants: it has no console to print snapshots to.
struct Callbacks {
    // Called for every collected snapshot. The console entry point uses this
    // to print; nothing else does.
    agent::Agent::SnapshotHandler onSnapshot{};
    // Called once the HTTP server is listening and collection has started.
    // The Windows Service reports SERVICE_RUNNING from here — the SCM kills a
    // service that has not reported it in time, so it has to fire at the point
    // the agent is genuinely up rather than after the wait loop ends.
    std::function<void()> onReady{};
};

// Starts the agent and its HTTP server, waits until shouldStop() returns true,
// then shuts both down. Returns the process exit code.
//
// The wait is a poll rather than a condition variable because the console
// entry point's stop signal arrives in a signal handler, which may only touch
// a sig_atomic_t. Extracted from main() so the console and the service share
// one lifecycle instead of two that drift apart.
int runUntilStopped(const agent::AgentConfig &config,
                    const std::function<bool()> &shouldStop,
                    Callbacks callbacks = {});

} // namespace runtime
