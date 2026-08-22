#pragma once

#include <cstdint>

#include "domain/CPUInfo.h"

class CPUCollector {
public:
    CPUCollector() = default;

    // Not const, unlike the other collectors: CPU usage is a rate, so each call
    // has to keep the sample that the next one measures its interval against.
    // The instance must therefore outlive a single collection cycle.
    CPUInfo collect();

private:
    double sampleUsagePercent();

    bool hasPreviousSample_{false};
    std::uint64_t previousIdleTicks_{0};
    std::uint64_t previousTotalTicks_{0};
    double lastUsagePercent_{0.0};
};
