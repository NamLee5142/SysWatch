#include <chrono>
#include <iostream>
#include <thread>
#include "agent/Agent.h"
#include "config/AgentConfig.h"
#include "http/HTTPServer.h"

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

    std::cout << "Agent started. Listening on 127.0.0.1:" << config.serverPort << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(5));

    agent.stop();
    server.stop();

    std::cout << "Agent stopped." << std::endl;
    return 0;
}
