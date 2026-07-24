#pragma once

#include "Snapshot.h"
#include "CPUCollector.h"
#include "MemoryCollector.h"
#include "DiskCollector.h"
#include "OsCollector.h"

class SnapshotCollector {
public:
    Snapshot collect() const {
        Snapshot snapshot;
        snapshot.cpuInfo = CPUCollector().collect();
        snapshot.memoryInfo = MemoryCollector().collect();
        snapshot.diskInfo = DiskCollector().collect();
        snapshot.systemInfo = OsCollector().collect();
        return snapshot;
    }
};
