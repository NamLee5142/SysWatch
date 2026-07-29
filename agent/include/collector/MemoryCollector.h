#pragma once

#include "domain/MemoryInfo.h"

class MemoryCollector {
public:
    MemoryCollector() = default;
    MemoryInfo collect() const;
};
