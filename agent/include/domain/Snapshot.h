#pragma once

#include "CPUInfo.h"
#include "MemoryInfo.h"
#include "DiskInfo.h"
#include "SystemInfo.h"

class Snapshot {
public:
    Snapshot() = default;

    CPUInfo cpuInfo;
    MemoryInfo memoryInfo;
    DiskInfo diskInfo;
    SystemInfo systemInfo;
};
