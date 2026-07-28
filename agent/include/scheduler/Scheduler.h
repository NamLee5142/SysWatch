#pragma once

#include <chrono>
#include <functional>

namespace agent {

class Scheduler {
public:
    using Callback = std::function<void()>;

    Scheduler(std::chrono::milliseconds interval, Callback callback);
    ~Scheduler();

    void start();
    void stop();

private:
    std::chrono::milliseconds interval_;
    Callback callback_;
    bool running_ = false;
};

} // namespace agent

