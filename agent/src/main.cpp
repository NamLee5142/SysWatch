#include <chrono>
#include <csignal>
#include <iostream>
#include <thread>
#include "agent/Agent.h"
#include "config/AgentConfig.h"
#include "http/HTTPServer.h"

namespace {

volatile std::sig_atomic_t stopRequested = 0;

extern "C" void handleStopSignal(int) {
    stopRequested = 1;
}

} // namespace

int main() {
    agent::AgentConfig config;
    config.collectionInterval = std::chrono::seconds(2);
    config.serverPort = 8080;

    agent::Agent agent(config, [](const auto &snapshot) {
        std::cout << "Snapshot: "
                  << "CPU=" << snapshot.cpuInfo.usagePercent << "% "
                  << "Memory=" << snapshot.memoryInfo.usedMB << "MB/" << snapshot.memoryInfo.totalMB << "MB "
                  << "Disk=" << snapshot.diskInfo.freeGB << "GB free/" << snapshot.diskInfo.totalGB << "GB "
                  << "System=" << snapshot.systemInfo.name << " " << snapshot.systemInfo.version
                  << std::endl;
    });

    http::HTTPServer server(agent, config.serverPort);

    server.start();
    agent.start();

    std::signal(SIGINT, handleStopSignal);
    std::signal(SIGTERM, handleStopSignal);

    std::cout << "Agent started. Listening on 127.0.0.1:" << config.serverPort
              << ". Press Ctrl+C to stop." << std::endl;

    // Run until interrupted. The signal handler may only touch a sig_atomic_t,
    // so poll the flag rather than waiting on a condition variable.
    while (stopRequested == 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }

    std::cout << "\nStopping agent." << std::endl;

    agent.stop();
    server.stop();

    std::cout << "Agent stopped." << std::endl;
    return 0;
}
