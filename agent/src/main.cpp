#include <chrono>
#include <csignal>
#include <iostream>
#include "config/AgentConfig.h"
#include "runtime/AgentRuntime.h"

namespace {

volatile std::sig_atomic_t stopRequested = 0;

extern "C" void handleStopSignal(int) {
    stopRequested = 1;
}

void printSnapshot(const Snapshot &snapshot) {
    std::cout << "Snapshot: "
              << "CPU=" << snapshot.cpuInfo.usagePercent << "% "
              << "Memory=" << snapshot.memoryInfo.usedMB << "MB/" << snapshot.memoryInfo.totalMB << "MB "
              << "Disk=" << snapshot.diskInfo.freeGB << "GB free/" << snapshot.diskInfo.totalGB << "GB "
              << "System=" << snapshot.systemInfo.name << " " << snapshot.systemInfo.version
              << std::endl;
}

} // namespace

int main() {
    agent::AgentConfig config;
    config.collectionInterval = std::chrono::seconds(2);
    config.serverPort = 8080;

    std::signal(SIGINT, handleStopSignal);
    std::signal(SIGTERM, handleStopSignal);

    // Everything the console entry point adds over the shared runtime: it
    // prints, and it stops on Ctrl+C. The lifecycle itself lives in
    // runUntilStopped so the Windows Service can reuse it unchanged.
    runtime::Callbacks callbacks;
    callbacks.onSnapshot = printSnapshot;
    callbacks.onReady = [&config] {
        std::cout << "Agent started. Listening on 127.0.0.1:" << config.serverPort
                  << ". Press Ctrl+C to stop." << std::endl;
    };

    const int result = runtime::runUntilStopped(
        config, [] { return stopRequested != 0; }, callbacks);

    std::cout << "\nAgent stopped." << std::endl;
    return result;
}
