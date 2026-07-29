#pragma once

class CPUInfo {
public:
    CPUInfo() = default;
    CPUInfo(int coreCount, double usagePercent)
        : coreCount(coreCount), usagePercent(usagePercent) {}

    int coreCount{0};
    double usagePercent{0.0};
};
