#include <iostream>
#include "SnapshotCollector.h"

int main() {
    SnapshotCollector collector;
    auto snapshot = collector.collect();
    (void)snapshot;

    std::cout << "Snapshot created successfully." << std::endl;
    return 0;
}
