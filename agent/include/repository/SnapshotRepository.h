#pragma once

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
    std::optional<Snapshot> latestSnapshot_;
};

} // namespace agent
