#pragma once

#include <cstdint>
#include <string>
#include <vector>

// One network interface's traffic. bytesSent / bytesRecv are the adapter's
// cumulative octet counters; the per-second rates are derived by the collector
// from the delta between successive samples, so a missed poll costs a rate
// reading but never the running totals.
class NetworkInterfaceInfo {
public:
    NetworkInterfaceInfo() = default;

    std::string name;
    std::uint64_t bytesSent{0};
    std::uint64_t bytesRecv{0};
    double bytesSentPerSec{0.0};
    double bytesRecvPerSec{0.0};
};

// Network activity at collection time: one entry per operational, non-loopback
// interface.
class NetworkInfo {
public:
    NetworkInfo() = default;

    std::vector<NetworkInterfaceInfo> interfaces;
};
