#include "scheduler/Scheduler.h"

namespace agent {

Scheduler::Scheduler(std::chrono::milliseconds interval, Task task)
    : interval_(interval), task_(std::move(task)) {}

Scheduler::~Scheduler() = default;

void Scheduler::start() {}

void Scheduler::stop() {}

} // namespace agent
