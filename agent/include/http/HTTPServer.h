#pragma once

#include "agent/Agent.h"
#include <thread>
#include <atomic>

namespace http {

class HTTPServer {
public:
    explicit HTTPServer(agent::Agent &agent);
    ~HTTPServer();

    void start();
    void stop();

private:
    agent::Agent &agent_;
    std::thread serverThread_;
    std::atomic<bool> running_{false};
};

} // namespace http
