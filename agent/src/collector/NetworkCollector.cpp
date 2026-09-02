#include "collector/NetworkCollector.h"

#include <iterator>
#include <unordered_set>
#include <utility>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2ipdef.h>
#include <windows.h>
#include <iphlpapi.h>
// GetIfTable2, MIB_IF_ROW2 and FreeMibTable. MinGW's iphlpapi.h only pulls
// netioapi.h in behind an NTDDI version gate that its own default target does
// not clear, and the header's guard is keyed on ws2ipdef.h being seen first —
// hence the include order here.
#include <netioapi.h>
#endif

namespace {

// Matches CPUCollector's floor and for the same reason: below it the counters
// have barely moved and the division is mostly rounding noise. A caller polling
// faster still gets the last real rate rather than a zero.
constexpr std::chrono::milliseconds kMinimumSampleInterval{100};

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

double perSecond(std::uint64_t current, std::uint64_t previous, double seconds) {
    // A counter that went backwards is a reset (or the adapter was replaced
    // under the same LUID); there is no meaningful rate to report for it.
    if (current < previous || seconds <= 0.0) {
        return 0.0;
    }
    return static_cast<double>(current - previous) / seconds;
}
#endif

} // namespace

NetworkInfo NetworkCollector::collect() {
    NetworkInfo info;

#ifdef _WIN32
    MIB_IF_TABLE2 *table = nullptr;
    if (GetIfTable2(&table) != NO_ERROR || table == nullptr) {
        return info;
    }

    const auto now = std::chrono::steady_clock::now();
    std::unordered_set<std::uint64_t> seen;

    for (ULONG i = 0; i < table->NumEntries; ++i) {
        const MIB_IF_ROW2 &row = table->Table[i];

        // GetIfTable2 returns a row per filter layer stacked on each adapter —
        // "Wi-Fi", "Wi-Fi-QoS Packet Scheduler", "Wi-Fi-Native WiFi Filter
        // Driver" and so on all carry the same counters. HardwareInterface
        // keeps only the physical NIC, so the summed throughput is not a
        // sixfold overcount. Loopback and non-operational interfaces go too.
        if (row.OperStatus != IfOperStatusUp ||
            row.Type == IF_TYPE_SOFTWARE_LOOPBACK ||
            !row.InterfaceAndOperStatusFlags.HardwareInterface ||
            row.InterfaceAndOperStatusFlags.FilterInterface) {
            continue;
        }

        const std::uint64_t luid = row.InterfaceLuid.Value;
        seen.insert(luid);

        NetworkInterfaceInfo entry;
        entry.name = toUtf8(row.Alias);
        entry.bytesRecv = row.InOctets;
        entry.bytesSent = row.OutOctets;

        auto previous = previousByLuid_.find(luid);
        if (previous == previousByLuid_.end()) {
            // First sighting of this interface: establish a baseline, report no
            // rate yet — there is no interval behind it.
            previousByLuid_.emplace(
                luid, InterfaceSample{row.InOctets, row.OutOctets, now, 0.0, 0.0});
        } else {
            InterfaceSample &sample = previous->second;
            const auto elapsed = now - sample.time;

            if (elapsed >= kMinimumSampleInterval) {
                const double seconds = std::chrono::duration<double>(elapsed).count();
                sample.recvPerSec = perSecond(row.InOctets, sample.inOctets, seconds);
                sample.sentPerSec = perSecond(row.OutOctets, sample.outOctets, seconds);
                sample.inOctets = row.InOctets;
                sample.outOctets = row.OutOctets;
                sample.time = now;
            }
            // Below the floor: leave the baseline untouched and replay the last
            // rate, so the next accepted sample measures the whole window.

            entry.bytesRecvPerSec = sample.recvPerSec;
            entry.bytesSentPerSec = sample.sentPerSec;
        }

        info.interfaces.push_back(std::move(entry));
    }

    FreeMibTable(table);

    // Forget interfaces that were not in this enumeration, so one that returns
    // later does not diff against a stale counter.
    for (auto it = previousByLuid_.begin(); it != previousByLuid_.end();) {
        it = seen.count(it->first) ? std::next(it) : previousByLuid_.erase(it);
    }
#endif

    return info;
}
