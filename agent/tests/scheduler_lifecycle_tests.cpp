#include "scheduler/Scheduler.h"
#include <cassert>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <iostream>
#include <mutex>
#include <thread>

static bool wait_for_count(std::atomic_int &count,
                           int target,
                           std::mutex &mutex,
                           std::condition_variable &cv,
                           std::chrono::milliseconds timeout) {
    auto deadline = std::chrono::steady_clock::now() + timeout;
    std::unique_lock<std::mutex> lock(mutex);
    return cv.wait_until(lock, deadline, [&] { return count.load() >= target; });
}

int main() {
    std::atomic_int count{0};
    std::mutex mutex;
    std::condition_variable cv;

    agent::Scheduler scheduler(std::chrono::milliseconds(100), [&] {
        ++count;
        cv.notify_all();
    });

    count = 0;
    scheduler.start();
    assert(wait_for_count(count, 1, mutex, cv, std::chrono::milliseconds(200)));
    assert(wait_for_count(count, 3, mutex, cv, std::chrono::milliseconds(500)));

    scheduler.stop();
    int countAfterStop = count.load();
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    assert(count.load() == countAfterStop);

    count = 0;
    scheduler.start();
    assert(wait_for_count(count, 2, mutex, cv, std::chrono::milliseconds(500)));
    scheduler.stop();
    countAfterStop = count.load();
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    assert(count.load() == countAfterStop);

    std::cout << "Scheduler lifecycle test passed." << std::endl;
    return 0;
}
