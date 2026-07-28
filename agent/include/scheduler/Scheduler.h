#pragma once

// Placeholder scheduler interface for future task orchestration.
class Scheduler {
public:
    virtual ~Scheduler() = default;
    virtual void schedule() = 0;
};

