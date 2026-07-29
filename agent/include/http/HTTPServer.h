#pragma once

#include "agent/Agent.h"

namespace http {

class HTTPServer {
public:
    explicit HTTPServer(agent::Agent &agent);
    ~HTTPServer();

    void start();
    void stop();

private:
    agent::Agent &agent_;
};

} // namespace http
