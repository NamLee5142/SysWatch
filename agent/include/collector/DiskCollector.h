#pragma once

#include "DiskInfo.h"

class DiskCollector {
public:
    DiskCollector() = default;
    DiskInfo collect() const;
};
