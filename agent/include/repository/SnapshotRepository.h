#pragma once

#include <mutex>
#include <optional>
#include "domain/Snapshot.h"

namespace agent {

// Lightweight repository for snapshot persistence.
class SnapshotRepository {
public:
    SnapshotRepository() = default;

    void save(const Snapshot &snapshot);
    std::optional<Snapshot> latest() const noexcept;

private:
    mutable std::mutex mutex_;
    std::optional<Snapshot> latestSnapshot_;
};

} // namespace agent
