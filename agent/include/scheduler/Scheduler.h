#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <thread>

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
    void run();

    std::chrono::milliseconds interval_;
    Task task_;
    std::atomic_bool running_{false};
    std::thread worker_;
    std::mutex mutex_;
    std::condition_variable cv_;
};

} // namespace agent

