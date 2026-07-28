#pragma once

#include "domain/SystemInfo.h"

class OsCollector {
public:
    OsCollector() = default;
    SystemInfo collect() const;
};
