#include "collector/ProcessCollector.h"

#include <algorithm>

#ifdef _WIN32
#include <windows.h>
#include <psapi.h>
#include <tlhelp32.h>
#endif

namespace {

// How many of the heaviest processes to keep. Detail for a dashboard panel,
// not a full table — the point is "what is using this machine", not an audit.
constexpr std::size_t kTopProcessCount = 10;

#ifdef _WIN32
std::string toUtf8(const wchar_t *value) {
    if (value == nullptr || value[0] == L'\0') {
        return {};
    }

    const int needed = WideCharToMultiByte(CP_UTF8, 0, value, -1, nullptr, 0, nullptr, nullptr);
    if (needed <= 1) {
        return {};
    }

    std::string result(static_cast<std::size_t>(needed - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, value, -1, result.data(), needed, nullptr, nullptr);
    return result;
}

std::uint64_t workingSetMB(DWORD pid) {
    // PROCESS_QUERY_LIMITED_INFORMATION is the least privilege that still reads
    // memory counters, and it succeeds for processes that the broader
    // PROCESS_QUERY_INFORMATION would be denied.
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (process == nullptr) {
        return 0;
    }

    PROCESS_MEMORY_COUNTERS counters{};
    std::uint64_t megabytes = 0;
    if (GetProcessMemoryInfo(process, &counters, sizeof(counters))) {
        megabytes = static_cast<std::uint64_t>(counters.WorkingSetSize) / (1024ULL * 1024ULL);
    }

    CloseHandle(process);
    return megabytes;
}
#endif

} // namespace

ProcessInfo ProcessCollector::collect() const {
    ProcessInfo info;

#ifdef _WIN32
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE) {
        return info;
    }

    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);

    if (Process32FirstW(snapshot, &entry)) {
        do {
            // The count is every process the walk sees, whether or not the
            // agent can open it to read its memory: a protected process it
            // cannot inspect is still a running process.
            ++info.count;

            info.top.push_back(ProcessEntry(
                static_cast<std::uint32_t>(entry.th32ProcessID),
                toUtf8(entry.szExeFile),
                workingSetMB(entry.th32ProcessID)));
        } while (Process32NextW(snapshot, &entry));
    }

    CloseHandle(snapshot);

    // Rank by memory, keep the heaviest few. Ties broken by pid so the order is
    // stable between cycles rather than dependent on enumeration order.
    std::sort(info.top.begin(), info.top.end(), [](const ProcessEntry &a, const ProcessEntry &b) {
        if (a.memoryMB != b.memoryMB) {
            return a.memoryMB > b.memoryMB;
        }
        return a.pid < b.pid;
    });

    if (info.top.size() > kTopProcessCount) {
        info.top.resize(kTopProcessCount);
    }
#endif

    return info;
}
