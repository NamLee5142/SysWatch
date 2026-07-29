#include "agent/Agent.h"
#include "scheduler/Scheduler.h"
#include <chrono>
#include <iostream>

namespace agent {

Agent::Agent(AgentConfig config)
    : config_(std::move(config)) {}

Agent::~Agent() = default;

void Agent::start() {
    if (scheduler_) {
        return;
    }

    scheduler_ = std::make_unique<Scheduler>(config_.collectionInterval, [this] {
        collectCycle();
    });
    scheduler_->start();
}

void Agent::stop() {
    if (!scheduler_) {
        return;
    }

    scheduler_->stop();
    scheduler_.reset();
}

#include <iostream>

void Agent::collectCycle() {
    auto snapshot = collector_.collect();
    repository_.save(snapshot);

    std::cout << "Snapshot: "
              << "CPU=" << snapshot.cpuInfo.usagePercent << "% "
              << "Memory=" << snapshot.memoryInfo.usedMB << "MB/" << snapshot.memoryInfo.totalMB << "MB "
              << "Disk=" << snapshot.diskInfo.freeGB << "GB free/" << snapshot.diskInfo.totalGB << "GB "
              << "System=" << snapshot.systemInfo.name << " " << snapshot.systemInfo.version
              << std::endl;
}

} // namespace agent
