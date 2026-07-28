#include "collector/MemoryCollector.h"
#ifdef _WIN32
#include <windows.h>
#endif

MemoryInfo MemoryCollector::collect() const {
    MemoryInfo info;
#ifdef _WIN32
    MEMORYSTATUSEX state;
    state.dwLength = sizeof(state);
    if (GlobalMemoryStatusEx(&state)) {
        std::uint64_t totalMB = state.ullTotalPhys / (1024ULL * 1024ULL);
        std::uint64_t availMB = state.ullAvailPhys / (1024ULL * 1024ULL);
        info.totalMB = totalMB;
        info.usedMB = totalMB - availMB;
    }
#endif
    return info;
}
