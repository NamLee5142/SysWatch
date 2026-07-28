#pragma once

#include "SystemInfo.h"

class OsCollector {
public:
    OsCollector() = default;
    SystemInfo collect() const;
};
