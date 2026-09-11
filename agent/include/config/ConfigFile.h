#pragma once

#include "config/AgentConfig.h"

#include <string>
#include <vector>

namespace config {

// Where the agent reads its settings from.
//
// The same file the backend reads, in the same place and the same format:
// %PROGRAMDATA%\SysWatch\syswatch.env, KEY=VALUE, # for a comment. On a machine
// running both, that is one file to write and one file to protect. On a machine
// running only the agent it holds only the agent's keys, and every key it does
// not recognise is ignored - which is what makes sharing the file work at all,
// because most of what is in it belongs to the backend.
//
// **There is deliberately no environment variable for any value.** The backend
// reads its settings from the environment first and the file second, and that
// is right for it: nothing it reads that way is a credential the machine did
// not already hold. The agent's token is different. A machine-wide environment
// variable on Windows is readable by every account on the box, and a service's
// environment is visible to anything that can open the process - so a token put
// there is a token shared with every local user, to save editing a file that
// the installer writes anyway.
//
// SYSWATCH_AGENT_CONFIG_FILE moves the *path*, because a test and a
// non-default install both need that and neither is a secret.
struct LoadResult {
    bool fileFound{false};
    // Lines that named a setting but could not be read as one. Reported rather
    // than guessed at: a port of "eighty-eighty" should be a message an
    // operator can act on, not a silent fallback to the default.
    std::vector<std::string> problems;
};

// The path the agent reads, honouring SYSWATCH_AGENT_CONFIG_FILE.
std::string defaultConfigPath();

// Applies whatever the file sets, leaving everything else at the value it
// already had. An absent file is not an error: it means the defaults, which is
// exactly what a single-machine install wants.
LoadResult loadInto(const std::string &path, agent::AgentConfig &config);

} // namespace config
