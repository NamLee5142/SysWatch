#pragma once

#include "CPUInfo.h"

class CPUCollector {
public:
    CPUCollector() = default;
    CPUInfo collect() const;
};
