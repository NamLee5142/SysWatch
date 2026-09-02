#pragma once

#include <chrono>

#include "CPUInfo.h"
#include "MemoryInfo.h"
#include "DiskInfo.h"
#include "SystemInfo.h"
#include "ProcessInfo.h"
#include "NetworkInfo.h"

class Snapshot {
public:
    Snapshot() = default;

    // When the metrics below were collected. Stamped by SnapshotCollector so the
    // value travels with the snapshot rather than being inferred downstream.
    std::chrono::system_clock::time_point collectedAt{};

    CPUInfo cpuInfo;
    MemoryInfo memoryInfo;
    DiskInfo diskInfo;
    SystemInfo systemInfo;
    ProcessInfo processInfo;
    NetworkInfo networkInfo;
};
