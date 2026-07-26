#include "OsCollector.h"
#ifdef _WIN32
#include <windows.h>
#endif

SystemInfo OsCollector::collect() const {
    SystemInfo info;
#ifdef _WIN32
    CHAR hostNameBuffer[MAX_COMPUTERNAME_LENGTH + 1];
    DWORD hostNameSize = sizeof(hostNameBuffer);
    if (GetComputerNameA(hostNameBuffer, &hostNameSize)) {
        info.hostName = std::string(hostNameBuffer, hostNameSize);
    }

    info.name = "Microsoft Windows";
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
