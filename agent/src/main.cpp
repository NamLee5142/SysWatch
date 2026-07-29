#include <chrono>
#include <iostream>
#include <thread>
#include "agent/Agent.h"
#include "config/AgentConfig.h"

int main() {
    agent::AgentConfig config;
    config.collectionInterval = std::chrono::seconds(2);

    agent::Agent agent(config);
    agent.start();

    std::cout << "Agent started." << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(5));
    agent.stop();

    std::cout << "Agent stopped." << std::endl;
    return 0;
}
