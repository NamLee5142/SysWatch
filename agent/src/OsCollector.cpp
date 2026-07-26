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

    // Use RtlGetVersion, which is not subject to the compatibility manifest version lie.
    using RtlGetVersionPtr = LONG (WINAPI*)(PRTL_OSVERSIONINFOW);
    constexpr LONG STATUS_SUCCESS = 0;

    HMODULE ntdll = GetModuleHandleA("ntdll.dll");
    if (ntdll) {
        auto rtlGetVersion = reinterpret_cast<RtlGetVersionPtr>(GetProcAddress(ntdll, "RtlGetVersion"));
        if (rtlGetVersion) {
            RTL_OSVERSIONINFOW versionInfo = {};
            versionInfo.dwOSVersionInfoSize = sizeof(versionInfo);
            if (rtlGetVersion(&versionInfo) == STATUS_SUCCESS) {
                info.version = std::to_string(versionInfo.dwMajorVersion) + "." + std::to_string(versionInfo.dwMinorVersion);
            }
        }
    }

    if (info.version.empty()) {
        info.version = "unknown";
    }
#endif
    return info;
}
