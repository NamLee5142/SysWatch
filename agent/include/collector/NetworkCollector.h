#pragma once

#include <chrono>
#include <cstdint>
#include <unordered_map>

#include "domain/NetworkInfo.h"

// Reports per-interface traffic. Not const, like CPUCollector: a throughput
// rate is a delta between samples, so the previous octet counters have to be
// kept per interface and the instance must outlive one collection cycle.
class NetworkCollector {
public:
    NetworkCollector() = default;

    NetworkInfo collect();

private:
    struct InterfaceSample {
        std::uint64_t inOctets{0};
        std::uint64_t outOctets{0};
        std::chrono::steady_clock::time_point time{};
        // The last rate actually computed for this interface, replayed while
        // calls come in faster than the minimum sample interval.
        double recvPerSec{0.0};
        double sentPerSec{0.0};
    };

    // Keyed by NET_LUID value. Entries for interfaces not seen in a cycle are
    // dropped, so an adapter that disappears and returns does not diff its new
    // counters against a stale baseline.
    std::unordered_map<std::uint64_t, InterfaceSample> previousByLuid_;
};
