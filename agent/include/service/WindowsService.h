#pragma once

#include "config/AgentConfig.h"

namespace service {

// The name the Service Control Manager knows this by. The install and
// uninstall commands use the same constants, so they cannot disagree about
// what they are managing.
constexpr const char *ServiceName = "SysWatchAgent";
constexpr const char *DisplayName = "SysWatch Agent";
constexpr const char *Description =
    "Collects CPU, memory, disk, process and network metrics and serves them "
    "to the SysWatch backend on 127.0.0.1.";

// Hands control to the Service Control Manager and runs the agent under it.
// Returns the process exit code.
//
// Only meaningful when the SCM started the process. Run from a console the
// dispatcher fails immediately, and that is reported rather than left as a
// process that appears to hang.
int runAsService(const agent::AgentConfig &config);

// Registers this executable with the Service Control Manager, set to start at
// boot and to restart itself if it fails. Returns the process exit code.
int install();

// Stops the service if it is running, then removes it. Leaves nothing behind
// except the log, which is the one thing worth keeping.
int uninstall();

} // namespace service
