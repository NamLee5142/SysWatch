#include "repository/SnapshotRepository.h"

namespace agent {

void SnapshotRepository::save(const Snapshot &snapshot) {
    std::lock_guard<std::mutex> lock(mutex_);
    latestSnapshot_ = snapshot;
}

std::optional<Snapshot> SnapshotRepository::latest() const noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    return latestSnapshot_;
}

} // namespace agent
