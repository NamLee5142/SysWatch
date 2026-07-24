#pragma once

#include <cstdint>

class MemoryInfo {
public:
    MemoryInfo() = default;
    MemoryInfo(std::uint64_t totalMB, std::uint64_t usedMB)
        : totalMB(totalMB), usedMB(usedMB) {}

    std::uint64_t totalMB{0};
    std::uint64_t usedMB{0};
};
