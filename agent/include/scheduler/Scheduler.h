#pragma once

#include <chrono>
#include <functional>

namespace agent {

class Scheduler {
public:
    using Task = std::function<void()>;

    Scheduler(std::chrono::milliseconds interval, Task task);
    ~Scheduler();

    Scheduler(const Scheduler&) = delete;
    Scheduler& operator=(const Scheduler&) = delete;

    void start();
    void stop();

private:
    std::chrono::milliseconds interval_;
    Task task_;
    std::atomic_bool running_{false};
};

} // namespace agent

