#include "runtime/CommandLine.h"

#include <cstring>

namespace runtime {

Mode parseMode(int argc, const char *const *argv) {
    if (argc <= 1) {
        return Mode::Console;
    }

    // One argument, and only the ones below. The agent has no configuration to
    // pass on the command line — a bind host is deliberately absent, and the
    // rest belongs in a config file.
    if (argc > 2) {
        return Mode::Unknown;
    }

    const char *argument = argv[1];

    if (std::strcmp(argument, "--service") == 0) {
        return Mode::Service;
    }
    if (std::strcmp(argument, "--help") == 0 || std::strcmp(argument, "-h") == 0) {
        return Mode::Help;
    }

    return Mode::Unknown;
}

const char *usage() {
    return "SysWatch Agent\n"
           "\n"
           "  agent.exe              Run in this console. Prints snapshots, stops on Ctrl+C.\n"
           "  agent.exe --service    Run under the Windows Service Control Manager.\n"
           "                         Started by the SCM, not by hand.\n"
           "  agent.exe --help       This message.\n";
}

} // namespace runtime
