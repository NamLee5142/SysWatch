#include "http/SnapshotJson.h"

#include <chrono>
#include <ctime>
#include <iomanip>
#include <sstream>

namespace http {

namespace {

std::string quoteJsonString(const std::string &value) {
    std::ostringstream out;
    out << '"';
    for (char c : value) {
        switch (c) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\b': out << "\\b"; break;
            case '\f': out << "\\f"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    out << "\\u" << std::hex << std::uppercase << std::setw(4) << std::setfill('0') << (int)c;
                } else {
                    out << c;
                }
                break;
        }
    }
    out << '"';
    return out.str();
}

// Renders a time point as ISO-8601 in UTC, e.g. 2026-08-12T11:15:27Z.
std::string formatIso8601Utc(std::chrono::system_clock::time_point when) {
    const std::time_t seconds = std::chrono::system_clock::to_time_t(when);

    std::tm utc{};
#if defined(_WIN32)
    gmtime_s(&utc, &seconds);
#else
    gmtime_r(&seconds, &utc);
#endif

    std::ostringstream out;
    out << std::put_time(&utc, "%Y-%m-%dT%H:%M:%SZ");
    return out.str();
}

std::string jsonFor(const CPUInfo &cpu) {
    std::ostringstream out;
    out << "{"
        << "\"coreCount\":" << cpu.coreCount << ","
        << "\"usagePercent\":" << cpu.usagePercent
        << "}";
    return out.str();
}

std::string jsonFor(const MemoryInfo &memory) {
    std::ostringstream out;
    out << "{"
        << "\"totalMB\":" << memory.totalMB << ","
        << "\"usedMB\":" << memory.usedMB
        << "}";
    return out.str();
}

std::string jsonFor(const DiskInfo &disk) {
    std::ostringstream out;
    out << "{"
        << "\"totalGB\":" << disk.totalGB << ","
        << "\"freeGB\":" << disk.freeGB
        << "}";
    return out.str();
}

std::string jsonFor(const SystemInfo &system) {
    std::ostringstream out;
    out << "{"
        << "\"name\":" << quoteJsonString(system.name) << ","
        << "\"version\":" << quoteJsonString(system.version) << ","
        << "\"hostName\":" << quoteJsonString(system.hostName)
        << "}";
    return out.str();
}

std::string jsonFor(const ProcessEntry &process) {
    std::ostringstream out;
    out << "{"
        << "\"pid\":" << process.pid << ","
        << "\"name\":" << quoteJsonString(process.name) << ","
        << "\"memoryMB\":" << process.memoryMB
        << "}";
    return out.str();
}

std::string jsonFor(const NetworkInterfaceInfo &nic) {
    std::ostringstream out;
    out << "{"
        << "\"name\":" << quoteJsonString(nic.name) << ","
        << "\"bytesSent\":" << nic.bytesSent << ","
        << "\"bytesRecv\":" << nic.bytesRecv << ","
        << "\"bytesSentPerSec\":" << nic.bytesSentPerSec << ","
        << "\"bytesRecvPerSec\":" << nic.bytesRecvPerSec
        << "}";
    return out.str();
}

// The snapshot emitter had only object serializers; a process list and an
// interface list are the first arrays on the wire.
template <typename T>
std::string jsonArray(const std::vector<T> &items) {
    std::ostringstream out;
    out << '[';
    for (std::size_t i = 0; i < items.size(); ++i) {
        if (i != 0) {
            out << ',';
        }
        out << jsonFor(items[i]);
    }
    out << ']';
    return out.str();
}

std::string jsonFor(const ProcessInfo &processes) {
    std::ostringstream out;
    out << "{"
        << "\"count\":" << processes.count << ","
        << "\"top\":" << jsonArray(processes.top)
        << "}";
    return out.str();
}

std::string jsonFor(const NetworkInfo &network) {
    std::ostringstream out;
    out << "{"
        << "\"interfaces\":" << jsonArray(network.interfaces)
        << "}";
    return out.str();
}

std::string renderSnapshot(const Snapshot &snapshot) {
    std::ostringstream out;
    out << "{"
        << "\"collectedAt\":" << quoteJsonString(formatIso8601Utc(snapshot.collectedAt)) << ","
        << "\"cpuInfo\":" << jsonFor(snapshot.cpuInfo) << ","
        << "\"memoryInfo\":" << jsonFor(snapshot.memoryInfo) << ","
        << "\"diskInfo\":" << jsonFor(snapshot.diskInfo) << ","
        << "\"systemInfo\":" << jsonFor(snapshot.systemInfo) << ","
        << "\"processInfo\":" << jsonFor(snapshot.processInfo) << ","
        << "\"networkInfo\":" << jsonFor(snapshot.networkInfo)
        << "}";
    return out.str();
}

} // namespace

std::string snapshotToJson(const Snapshot &snapshot) {
    return renderSnapshot(snapshot);
}

} // namespace http
