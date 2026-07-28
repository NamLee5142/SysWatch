#include "repository/SnapshotRepository.h"

namespace agent {

void SnapshotRepository::save(const Snapshot &snapshot) {
    latestSnapshot_ = snapshot;
}

std::optional<Snapshot> SnapshotRepository::latest() const noexcept {
    return latestSnapshot_;
}

} // namespace agent
