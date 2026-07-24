#pragma once

#include <string>

class SystemInfo {
public:
    SystemInfo() = default;
    SystemInfo(std::string name, std::string version)
        : name(std::move(name)), version(std::move(version)) {}

    std::string name;
    std::string version;
};
