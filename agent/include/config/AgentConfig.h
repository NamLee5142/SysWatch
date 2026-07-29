#pragma once

#include <chrono>
#include <string>

namespace agent {

struct AgentConfig {
    std::chrono::milliseconds collectionInterval{std::chrono::seconds(1)};
    unsigned short serverPort{8080};
    std::string logPath{"logs/syswatch.log"};
};

} // namespace agent
