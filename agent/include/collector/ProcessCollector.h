#pragma once

#include "domain/ProcessInfo.h"

// Enumerates running processes and reports the count plus the heaviest few by
// memory. const, like the memory and disk collectors: the ranking is a plain
// read each cycle with no state carried between calls.
class ProcessCollector {
public:
    ProcessCollector() = default;
    ProcessInfo collect() const;
};
