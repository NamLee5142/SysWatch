#pragma once

#include <memory>
#include "collector/SnapshotCollector.h"

namespace agent {

class Scheduler;
class SnapshotRepository;

class Agent {
public:
    Agent();
    ~Agent();

    void start();
    void stop();

private:
    SnapshotCollector collector_;
    std::unique_ptr<SnapshotRepository> repository_;
    std::unique_ptr<Scheduler> scheduler_;
};

} // namespace agent
