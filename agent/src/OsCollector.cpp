#include "OsCollector.h"
#ifdef _WIN32
#include <windows.h>
#endif

SystemInfo OsCollector::collect() const {
    SystemInfo info;
#ifdef _WIN32
    CHAR nameBuffer[MAX_COMPUTERNAME_LENGTH + 1];
    DWORD size = sizeof(nameBuffer);
    if (GetComputerNameA(nameBuffer, &size)) {
        info.name = std::string(nameBuffer, size);
    } else {
        info.name = "Windows";
    }

    OSVERSIONINFOA osvi = {};
    osvi.dwOSVersionInfoSize = sizeof(osvi);
    if (GetVersionExA(&osvi)) {
        info.version = std::to_string(osvi.dwMajorVersion) + "." + std::to_string(osvi.dwMinorVersion);
    } else {
        info.version = "unknown";
    }
#endif
    return info;
}
