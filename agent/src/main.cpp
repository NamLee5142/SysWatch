#include <chrono>
#include <csignal>
#include <iostream>
#include "config/AgentConfig.h"
#include "runtime/AgentRuntime.h"
#include "runtime/CommandLine.h"
#include "service/WindowsService.h"

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

int runInConsole(const agent::AgentConfig &config) {
    std::signal(SIGINT, handleStopSignal);
    std::signal(SIGTERM, handleStopSignal);

    // Everything the console adds over the shared runtime: it prints snapshots,
    // and it stops on Ctrl+C. The lifecycle itself lives in runUntilStopped, so
    // the service reuses it unchanged.
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

} // namespace

int main(int argc, char **argv) {
    agent::AgentConfig config;
    config.collectionInterval = std::chrono::seconds(2);
    config.serverPort = 8080;

    switch (runtime::parseMode(argc, argv)) {
        case runtime::Mode::Service:
            return service::runAsService(config);

        case runtime::Mode::Help:
            std::cout << runtime::usage();
            return 0;

        case runtime::Mode::Unknown:
            std::cerr << runtime::usage();
            return 2;

        case runtime::Mode::Console:
        default:
            return runInConsole(config);
    }
}
