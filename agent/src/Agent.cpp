#include "agent/Agent.h"
#include "scheduler/Scheduler.h"
#include <chrono>

namespace agent {

Agent::Agent() = default;
Agent::~Agent() = default;

void Agent::start() {
    if (scheduler_) {
        return;
    }

    scheduler_ = std::make_unique<Scheduler>(std::chrono::seconds(1), [this] {
        auto snapshot = collector_.collect();
        repository_.save(snapshot);
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

} // namespace agent
