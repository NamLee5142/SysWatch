#pragma once

#include "MemoryInfo.h"

class MemoryCollector {
public:
    MemoryCollector() = default;
    MemoryInfo collect() const;
};
