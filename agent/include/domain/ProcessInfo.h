#pragma once

#include <cstdint>
#include <string>
#include <vector>

// One process in the "top" list. Ranked by memory rather than CPU: working set
// is a single stateless read per process, whereas per-process CPU needs
// GetProcessTimes deltas tracked across a PID set that recycles between samples.
class ProcessEntry {
public:
    ProcessEntry() = default;
    ProcessEntry(std::uint32_t pid, std::string name, std::uint64_t memoryMB)
        : pid(pid), name(std::move(name)), memoryMB(memoryMB) {}

    std::uint32_t pid{0};
    std::string name;
    std::uint64_t memoryMB{0};
};

// Process activity at collection time: the total count of running processes,
// and the few heaviest by memory. The count comes from the full process walk,
// independent of how many entries the agent could open to inspect.
class ProcessInfo {
public:
    ProcessInfo() = default;

    int count{0};
    std::vector<ProcessEntry> top;
};
