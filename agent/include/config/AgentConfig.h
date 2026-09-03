#pragma once

#include <chrono>
#include <string>

namespace agent {

struct AgentConfig {
    std::chrono::milliseconds collectionInterval{std::chrono::seconds(1)};
    // Port only — there is deliberately no bind-host field. HTTPServer always
    // binds 127.0.0.1, because the agent serves every collected metric with no
    // authentication of its own; SysWatch authenticates at the backend instead.
    // A configurable host would be a footgun whose only new setting is the one
    // that publishes the machine's telemetry to the network. See the comment in
    // HTTPServer::start() and http_server_bind_tests.cpp.
    unsigned short serverPort{8080};
    std::string logPath{"logs/syswatch.log"};
};

} // namespace agent
