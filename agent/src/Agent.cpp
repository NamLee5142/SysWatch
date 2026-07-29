#include "agent/Agent.h"
#include "scheduler/Scheduler.h"
#include <chrono>

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

void Agent::collectCycle() {
    auto snapshot = collector_.collect();
    repository_.save(snapshot);
}

} // namespace agent
