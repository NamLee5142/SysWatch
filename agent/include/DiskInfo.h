#pragma once

#include <cstdint>

class DiskInfo {
public:
    DiskInfo() = default;
    DiskInfo(std::uint64_t totalGB, std::uint64_t freeGB)
        : totalGB(totalGB), freeGB(freeGB) {}

    std::uint64_t totalGB{0};
    std::uint64_t freeGB{0};
};
