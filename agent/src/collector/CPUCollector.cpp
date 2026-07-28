#include "collector/CPUCollector.h"
#ifdef _WIN32
#include <windows.h>
#endif

CPUInfo CPUCollector::collect() const {
    CPUInfo info;
#ifdef _WIN32
    SYSTEM_INFO sysinfo;
    GetSystemInfo(&sysinfo);
    info.coreCount = static_cast<int>(sysinfo.dwNumberOfProcessors);
    info.usagePercent = 0.0; // placeholder; accurate CPU usage requires PDH or performance counters
#endif
    return info;
}
