#pragma once

#include <functional>
#include <memory>
#include <optional>
#include "collector/SnapshotCollector.h"
#include "config/AgentConfig.h"
#include "repository/SnapshotRepository.h"

namespace agent {

class Scheduler;

class Agent {
public:
    using SnapshotHandler = std::function<void(const Snapshot&)>;

    explicit Agent(AgentConfig config = {}, SnapshotHandler onSnapshot = {});
    ~Agent();

    void start();
    void stop();

    std::optional<Snapshot> latestSnapshot() const;

private:
    void collectCycle();

    AgentConfig config_;
    SnapshotCollector collector_;
    SnapshotRepository repository_;
    std::unique_ptr<Scheduler> scheduler_;
    SnapshotHandler onSnapshot_;
};

} // namespace agent
