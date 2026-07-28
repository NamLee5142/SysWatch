#pragma once

#include "domain/Snapshot.h"

// Lightweight repository for snapshot persistence.
class SnapshotRepository {
public:
    SnapshotRepository() = default;
    void save(const Snapshot &snapshot);
};
