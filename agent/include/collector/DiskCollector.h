#pragma once

#include "domain/DiskInfo.h"

class DiskCollector {
public:
    DiskCollector() = default;
    DiskInfo collect() const;
};
