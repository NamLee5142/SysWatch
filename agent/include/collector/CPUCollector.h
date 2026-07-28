#pragma once

#include "domain/CPUInfo.h"

class CPUCollector {
public:
    CPUCollector() = default;
    CPUInfo collect() const;
};
