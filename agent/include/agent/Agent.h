#pragma once

#include <memory>
#include "collector/SnapshotCollector.h"
#include "config/AgentConfig.h"
#include "repository/SnapshotRepository.h"

namespace agent {

class Scheduler;

class Agent {
public:
    explicit Agent(AgentConfig config = {});
    ~Agent();

    void start();
    void stop();

private:
    void collectCycle();

    AgentConfig config_;
    SnapshotCollector collector_;
    SnapshotRepository repository_;
    std::unique_ptr<Scheduler> scheduler_;
};

} // namespace agent
