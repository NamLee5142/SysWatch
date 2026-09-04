// The seam the Windows Service will hang off.
//
// runUntilStopped() is what the console entry point and the service both call,
// so the lifecycle exists once rather than twice. If these two ever drift
// apart, one of them stops shutting down cleanly and nobody notices until a
// machine will not reboot.

#include "runtime/AgentRuntime.h"
#include "config/AgentConfig.h"
#include <atomic>
#include <cassert>
#include <chrono>
#include <iostream>
#include <thread>

namespace {

agent::AgentConfig testConfig(unsigned short port) {
    agent::AgentConfig config;
    config.collectionInterval = std::chrono::milliseconds(50);
    config.serverPort = port;
    return config;
}

// Stopping immediately: the loop must not run a single unnecessary pass.
void stopsWhenAskedTo() {
    const int result = runtime::runUntilStopped(testConfig(54331), [] { return true; });
    assert(result == 0);
}

// Stopping later: the flag is what ends it, not a timeout.
void keepsRunningUntilTheFlagIsSet() {
    std::atomic<bool> stop{false};
    std::atomic<bool> finished{false};

    std::thread worker([&] {
        runtime::runUntilStopped(testConfig(54332), [&] { return stop.load(); });
        finished = true;
    });

    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    assert(!finished.load() && "the runtime returned without being asked to stop");

    stop = true;
    worker.join();
    assert(finished.load());
}

// The service reports SERVICE_RUNNING from here. The SCM kills a service that
// has not reported it in time, so it has to fire while the agent is coming up
// rather than after the wait loop ends.
void reportsReadyBeforeWaiting() {
    std::atomic<bool> ready{false};

    runtime::Callbacks callbacks;
    callbacks.onReady = [&] { ready = true; };

    runtime::runUntilStopped(testConfig(54333), [&] { return ready.load(); }, callbacks);

    assert(ready.load() && "onReady never fired");
}

// The console prints snapshots; the service passes nothing and must not crash
// for the lack of a handler.
void survivesWithoutCallbacks() {
    std::atomic<int> passes{0};

    runtime::runUntilStopped(testConfig(54334), [&] { return ++passes > 2; });
}

} // namespace

int main() {
    stopsWhenAskedTo();
    keepsRunningUntilTheFlagIsSet();
    reportsReadyBeforeWaiting();
    survivesWithoutCallbacks();

    std::cout << "Agent runtime tests passed." << std::endl;
    return 0;
}
