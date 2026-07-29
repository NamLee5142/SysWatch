#pragma once

#include "domain/Snapshot.h"
#include "CPUCollector.h"
#include "MemoryCollector.h"
#include "DiskCollector.h"
#include "OsCollector.h"

class SnapshotCollector {
public:
    SnapshotCollector() = default;

    Snapshot collect() const {
        Snapshot snapshot;
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
