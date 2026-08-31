#include "collector/CPUCollector.h"

#include <algorithm>
#include <chrono>
#ifdef _WIN32
#include <windows.h>
#endif

namespace {

#ifdef _WIN32
// A FILETIME is a 64-bit count of 100ns intervals delivered as two 32-bit
// halves; ULARGE_INTEGER is the documented way to put it back together.
std::uint64_t toTicks(const FILETIME &value) {
    ULARGE_INTEGER converted;
    converted.LowPart = value.dwLowDateTime;
    converted.HighPart = value.dwHighDateTime;
    return converted.QuadPart;
}
#endif

double clampPercent(double value) {
    return std::min(100.0, std::max(0.0, value));
}

// Windows accounts CPU time in ~15.6ms scheduler ticks, so an interval spanning
// only one or two of them is mostly rounding error — it can read 0% on a busy
// machine or 100% on an idle one depending on which core happened to tick.
// Below this floor there is nothing worth measuring, so the previous reading
// stands. Comfortably under AgentConfig::collectionInterval, which defaults to
// one second.
constexpr std::chrono::milliseconds kMinimumSampleInterval{100};

} // namespace

CPUInfo CPUCollector::collect() {
    CPUInfo info;
#ifdef _WIN32
    SYSTEM_INFO sysinfo;
    GetSystemInfo(&sysinfo);
    info.coreCount = static_cast<int>(sysinfo.dwNumberOfProcessors);
    info.usagePercent = sampleUsagePercent();
#endif
    return info;
}

double CPUCollector::sampleUsagePercent() {
#ifdef _WIN32
    const auto now = std::chrono::steady_clock::now();

    // Checked before reading the counters, and it leaves the baseline
    // untouched: the next accepted sample then measures across the whole
    // accumulated window instead of the sliver since the last rapid call. A
    // caller polling faster than the floor still gets a fresh reading every
    // kMinimumSampleInterval rather than a permanently frozen one.
    if (hasPreviousSample_ && now - previousSampleTime_ < kMinimumSampleInterval) {
        return lastUsagePercent_;
    }

    FILETIME idle;
    FILETIME kernel;
    FILETIME user;

    if (!GetSystemTimes(&idle, &kernel, &user)) {
        return lastUsagePercent_;
    }

    // Kernel time already includes idle time, so kernel + user is the whole
    // interval across all cores and idle is the share of it spent doing nothing.
    const std::uint64_t idleTicks = toTicks(idle);
    const std::uint64_t totalTicks = toTicks(kernel) + toTicks(user);

    const bool hadPreviousSample = hasPreviousSample_;
    const std::uint64_t idleDelta = idleTicks - previousIdleTicks_;
    const std::uint64_t totalDelta = totalTicks - previousTotalTicks_;

    hasPreviousSample_ = true;
    previousSampleTime_ = now;
    previousIdleTicks_ = idleTicks;
    previousTotalTicks_ = totalTicks;

    // Usage is a rate. The first call establishes the baseline and has no
    // interval to report on yet; the second call is the first real reading.
    if (!hadPreviousSample) {
        return 0.0;
    }

    // Defensive: the interval floor above should already have ruled this out.
    if (totalDelta == 0) {
        return lastUsagePercent_;
    }

    const double busyRatio =
        1.0 - static_cast<double>(idleDelta) / static_cast<double>(totalDelta);

    lastUsagePercent_ = clampPercent(100.0 * busyRatio);
    return lastUsagePercent_;
#else
    return 0.0;
#endif
}
