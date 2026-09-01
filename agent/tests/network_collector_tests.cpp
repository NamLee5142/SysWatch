#include "collector/NetworkCollector.h"
#include <cassert>
#include <chrono>
#include <cmath>
#include <iostream>
#include <thread>
#include <unordered_map>

static bool isFiniteNonNegative(double value) {
    return std::isfinite(value) && value >= 0.0;
}

int main() {
    NetworkCollector collector;

    // First sighting of every interface: a rate needs an interval behind it,
    // and there is none yet.
    NetworkInfo first = collector.collect();
    for (const NetworkInterfaceInfo &nic : first.interfaces) {
        assert(nic.bytesRecvPerSec == 0.0);
        assert(nic.bytesSentPerSec == 0.0);
        assert(!nic.name.empty());
    }

    std::unordered_map<std::string, std::uint64_t> recvAtFirst;
    for (const NetworkInterfaceInfo &nic : first.interfaces) {
        recvAtFirst[nic.name] = nic.bytesRecv;
    }

    // Past the sample floor the collector measures again.
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    NetworkInfo second = collector.collect();
    for (const NetworkInterfaceInfo &nic : second.interfaces) {
        assert(isFiniteNonNegative(nic.bytesRecvPerSec));
        assert(isFiniteNonNegative(nic.bytesSentPerSec));

        // Cumulative counters only ever climb within a test's lifetime.
        auto previous = recvAtFirst.find(nic.name);
        if (previous != recvAtFirst.end()) {
            assert(nic.bytesRecv >= previous->second);
        }
    }

    // A burst of calls inside the floor cannot remeasure: each repeats the
    // last accepted rate untouched.
    std::unordered_map<std::string, double> recvRateAfterSecond;
    for (const NetworkInterfaceInfo &nic : second.interfaces) {
        recvRateAfterSecond[nic.name] = nic.bytesRecvPerSec;
    }

    int rapidCalls = 0;
    auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(50);
    while (std::chrono::steady_clock::now() < deadline) {
        for (const NetworkInterfaceInfo &nic : collector.collect().interfaces) {
            auto expected = recvRateAfterSecond.find(nic.name);
            if (expected != recvRateAfterSecond.end()) {
                assert(nic.bytesRecvPerSec == expected->second);
            }
        }
        ++rapidCalls;
    }
    assert(rapidCalls > 0);

    std::cout << "Network collector test passed. interfaces=" << second.interfaces.size()
              << std::endl;
    return 0;
}
