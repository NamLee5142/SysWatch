#pragma once

#include "domain/Snapshot.h"

// Placeholder repository interface for future snapshot persistence.
class SnapshotRepository {
public:
    virtual ~SnapshotRepository() = default;
    virtual void save(const Snapshot &snapshot) = 0;
};
