#include "scheduler/Scheduler.h"
#include <cassert>
#include <chrono>
#include <iostream>
#include <thread>

int main() {
    int count = 0;
    agent::Scheduler scheduler(std::chrono::milliseconds(100), [&] { ++count; });

    scheduler.start();
    std::this_thread::sleep_for(std::chrono::milliseconds(350));
    scheduler.stop();

    assert(count >= 2 && count <= 5);

    scheduler.start();
    count = 0;
    std::this_thread::sleep_for(std::chrono::milliseconds(250));
    scheduler.stop();

    assert(count >= 2 && count <= 4);

    std::cout << "Scheduler lifecycle test passed." << std::endl;
    return 0;
}
