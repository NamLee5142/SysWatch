#pragma once

#include <string>

class SystemInfo {
public:
    SystemInfo() = default;
    SystemInfo(std::string name, std::string version, std::string hostName = {})
        : name(std::move(name)), version(std::move(version)), hostName(std::move(hostName)) {}

    std::string name;
    std::string version;
    std::string hostName;
};
