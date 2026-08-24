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

    // Sampling faster than the scheduler ticks has no interval worth measuring:
    // the counters barely move, and dividing by that near-zero delta yields
    // rounding noise rather than a reading. Every call inside the collector's
    // minimum interval must repeat the last real value untouched.
    int rapidCalls = 0;
    auto rapidDeadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(50);
    while (std::chrono::steady_clock::now() < rapidDeadline) {
        assert(collector.collect().usagePercent == underLoad.usagePercent);
        ++rapidCalls;
    }
    assert(rapidCalls > 0);

    // Past the minimum interval it measures again, across the whole window the
    // rapid calls accumulated rather than a sliver of it.
    burnCpu(std::chrono::milliseconds(300));
    double afterRapidSampling = collector.collect().usagePercent;
    assert(isValidPercent(afterRapidSampling));
    assert(afterRapidSampling > 0.0);

    // Sampling state belongs to the instance, not to the process: a fresh
    // collector starts from its own baseline even after another has been used.
    CPUCollector second;
    assert(second.collect().usagePercent == 0.0);

    std::cout << "CPU collector sampling test passed." << std::endl;
    return 0;
}
