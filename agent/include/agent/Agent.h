#pragma once

#include <memory>
#include "collector/SnapshotCollector.h"
#include "repository/SnapshotRepository.h"

namespace agent {

class Scheduler;

class Agent {
public:
    Agent();
    ~Agent();

    void start();
    void stop();

private:
    SnapshotCollector collector_;
    SnapshotRepository repository_;
    std::unique_ptr<Scheduler> scheduler_;
};

} // namespace agent
