#include <cassert>
#include <cstring>
#include <iostream>
#include <string>

// SYSWATCH_VERSION is a compile definition set from the repository's VERSION
// file by CMake. Nothing in the C++ fails to build without it — the startup log
// would simply stop naming a version, and the first anyone would notice is a
// support log from a machine in the field that does not say what it is running.
#ifndef SYSWATCH_VERSION
#error "SYSWATCH_VERSION is not defined; CMake should set it from ../VERSION"
#endif

int main() {
    const std::string version = SYSWATCH_VERSION;

    assert(!version.empty());

    // MAJOR.MINOR.PATCH, the same shape scripts/sync_version.py enforces and
    // CMake's project(VERSION) requires.
    const std::size_t first = version.find('.');
    const std::size_t second = version.find('.', first + 1);
    assert(first != std::string::npos);
    assert(second != std::string::npos);
    assert(version.find('.', second + 1) == std::string::npos);

    for (const char character : version) {
        assert(std::isdigit(static_cast<unsigned char>(character)) || character == '.');
    }

    std::cout << "Version test passed: " << version << std::endl;
    return 0;
}
