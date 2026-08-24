#include "collector/CPUCollector.h"
#include <cassert>
#include <chrono>
#include <cmath>
#include <iostream>

// Keeps the CPU genuinely busy for a while. volatile so the loop survives the
// optimiser, which would otherwise delete the only thing this test measures.
static void burnCpu(std::chrono::milliseconds duration) {
    volatile double sink = 0.0;
    auto deadline = std::chrono::steady_clock::now() + duration;
    while (std::chrono::steady_clock::now() < deadline) {
        sink += 1.0;
    }
}

static bool isValidPercent(double value) {
    return std::isfinite(value) && value >= 0.0 && value <= 100.0;
}

int main() {
    CPUCollector collector;

    // Usage is a rate, so the first call has no interval behind it and only
    // establishes the baseline the next call measures against.
    CPUInfo baseline = collector.collect();
    assert(baseline.usagePercent == 0.0);
    assert(baseline.coreCount > 0);

    burnCpu(std::chrono::milliseconds(300));

    CPUInfo underLoad = collector.collect();
    assert(underLoad.usagePercent > 0.0);
    assert(isValidPercent(underLoad.usagePercent));
    assert(underLoad.coreCount == baseline.coreCount);

    // Sampling faster than the counter advances leaves a zero delta to divide
    // by. That must not produce a NaN, an infinity, or an out-of-range reading.
    for (int i = 0; i < 200; ++i) {
        assert(isValidPercent(collector.collect().usagePercent));
    }

    // Sampling state belongs to the instance, not to the process: a fresh
    // collector starts from its own baseline even after another has been used.
    CPUCollector second;
    assert(second.collect().usagePercent == 0.0);

    std::cout << "CPU collector sampling test passed." << std::endl;
    return 0;
}
