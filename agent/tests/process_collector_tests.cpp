#include "collector/ProcessCollector.h"
#include <cassert>
#include <iostream>

int main() {
    ProcessCollector collector;
    ProcessInfo info = collector.collect();

    // Any running machine has processes. Zero would mean the walk never
    // started, not an idle system.
    assert(info.count > 0);

    // The top list is a bounded panel, not the whole table.
    assert(info.top.size() <= 10);

    // And it cannot claim more entries than the machine is running.
    assert(static_cast<int>(info.top.size()) <= info.count);

    std::uint64_t previousMemory = ~0ULL;
    for (const ProcessEntry &entry : info.top) {
        // Ranked heaviest first: each entry uses no more memory than the one
        // before it.
        assert(entry.memoryMB <= previousMemory);
        previousMemory = entry.memoryMB;

        // A process the walk returned has a name; an empty one means the
        // wide-to-UTF-8 conversion dropped it.
        assert(!entry.name.empty());
    }

    std::cout << "Process collector test passed. count=" << info.count
              << " top=" << info.top.size() << std::endl;
    return 0;
}
