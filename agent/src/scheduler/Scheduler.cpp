#include "scheduler/Scheduler.h"

namespace agent {

Scheduler::Scheduler(std::chrono::milliseconds interval, Task task)
    : interval_(interval), task_(std::move(task)) {}

Scheduler::~Scheduler() {
    stop();
}

void Scheduler::start() {
    bool expected = false;
    if (!running_.compare_exchange_strong(expected, true)) {
        return;
    }

    worker_ = std::thread([this] { run(); });
}

void Scheduler::stop() {
    bool expected = true;
    if (!running_.compare_exchange_strong(expected, false)) {
        return;
    }

    {
        std::lock_guard<std::mutex> lock(mutex_);
        cv_.notify_all();
    }

    if (worker_.joinable()) {
        worker_.join();
    }
}

void Scheduler::run() {
    auto nextWake = std::chrono::steady_clock::now();

    while (running_) {
        try {
            task_();
        } catch (...) {
            // Swallow exceptions to keep the worker thread alive.
            // Scheduler should not terminate the process if a scheduled task throws.
        }

        nextWake += interval_;
        std::unique_lock<std::mutex> lock(mutex_);
        cv_.wait_until(lock, nextWake, [this] { return !running_; });
    }
}

} // namespace agent
