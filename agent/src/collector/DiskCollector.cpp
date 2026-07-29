#include "collector/DiskCollector.h"
#ifdef _WIN32
#include <windows.h>
#endif

DiskInfo DiskCollector::collect() const {
    DiskInfo info;
#ifdef _WIN32
    ULARGE_INTEGER freeBytesAvailable, totalNumberOfBytes, totalNumberOfFreeBytes;
    // Use C:\ as a reasonable default for MVP
    if (GetDiskFreeSpaceExA("C:\\", &freeBytesAvailable, &totalNumberOfBytes, &totalNumberOfFreeBytes)) {
        info.totalGB = static_cast<std::uint64_t>(totalNumberOfBytes.QuadPart / (1024ULL * 1024ULL * 1024ULL));
        info.freeGB = static_cast<std::uint64_t>(totalNumberOfFreeBytes.QuadPart / (1024ULL * 1024ULL * 1024ULL));
    }
#endif
    return info;
}
