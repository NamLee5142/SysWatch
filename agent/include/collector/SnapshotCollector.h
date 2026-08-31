#pragma once

#include <chrono>

#include "domain/Snapshot.h"
#include "CPUCollector.h"
#include "MemoryCollector.h"
#include "DiskCollector.h"
#include "OsCollector.h"

class SnapshotCollector {
public:
    SnapshotCollector() = default;

    // Not const: CPUCollector has to carry sampling state between calls.
    Snapshot collect() {
        Snapshot snapshot;
        snapshot.collectedAt = std::chrono::system_clock::now();
        snapshot.cpuInfo = cpuCollector.collect();
        snapshot.memoryInfo = memoryCollector.collect();
        snapshot.diskInfo = diskCollector.collect();
        snapshot.systemInfo = osCollector.collect();
        return snapshot;
    }

private:
    CPUCollector cpuCollector;
    MemoryCollector memoryCollector;
    DiskCollector diskCollector;
    OsCollector osCollector;
};
