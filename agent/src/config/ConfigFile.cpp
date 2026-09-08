#include "config/ConfigFile.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <fstream>
#include <string>

namespace config {

namespace {

constexpr const char *PathVariable = "SYSWATCH_AGENT_CONFIG_FILE";
constexpr const char *FileName = "syswatch.env";

std::string trimmed(const std::string &value) {
    const auto begin = value.find_first_not_of(" \t\r\n");
    if (begin == std::string::npos) {
        return "";
    }
    const auto end = value.find_last_not_of(" \t\r\n");
    return value.substr(begin, end - begin + 1);
}

// A value may be quoted, which is how a path with a trailing space or a token
// somebody pasted with quotation marks around it survives. Only a matching
// pair is stripped: a lone quote is part of the value, because guessing which
// end was meant is worse than keeping it.
std::string unquoted(const std::string &value) {
    if (value.size() >= 2 && value.front() == value.back() &&
        (value.front() == '"' || value.front() == '\'')) {
        return value.substr(1, value.size() - 2);
    }
    return value;
}

bool asBool(const std::string &value, bool &out) {
    std::string lowered = value;
    std::transform(lowered.begin(), lowered.end(), lowered.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });

    if (lowered == "true" || lowered == "1" || lowered == "yes" || lowered == "on") {
        out = true;
        return true;
    }
    if (lowered == "false" || lowered == "0" || lowered == "no" || lowered == "off") {
        out = false;
        return true;
    }
    return false;
}

bool asLong(const std::string &value, long long &out) {
    if (value.empty()) {
        return false;
    }
    const bool digits = std::all_of(value.begin(), value.end(), [](unsigned char c) {
        return std::isdigit(c) != 0;
    });
    if (!digits) {
        return false;
    }
    out = std::atoll(value.c_str());
    return true;
}

} // namespace

std::string defaultConfigPath() {
    if (const char *explicitPath = std::getenv(PathVariable)) {
        if (*explicitPath != '\0') {
            return explicitPath;
        }
    }

#if defined(_WIN32)
    if (const char *programData = std::getenv("PROGRAMDATA")) {
        return std::string(programData) + "\\SysWatch\\" + FileName;
    }
#endif
    return FileName;
}

LoadResult loadInto(const std::string &path, agent::AgentConfig &config) {
    LoadResult result;

    std::ifstream file(path);
    if (!file.is_open()) {
        // Absent is the single-machine case and is not worth a word.
        return result;
    }
    result.fileFound = true;

    std::string line;
    while (std::getline(file, line)) {
        const std::string trimmedLine = trimmed(line);
        if (trimmedLine.empty() || trimmedLine[0] == '#') {
            continue;
        }

        const std::size_t equals = trimmedLine.find('=');
        if (equals == std::string::npos) {
            continue;
        }

        const std::string key = trimmed(trimmedLine.substr(0, equals));
        const std::string value = unquoted(trimmed(trimmedLine.substr(equals + 1)));

        // Every unrecognised key is skipped in silence. Most of this file
        // belongs to the backend, and an agent that complained about
        // SYSWATCH_SESSION_SECRET would be complaining about a correctly
        // configured machine.
        if (key == "SYSWATCH_AGENT_BACKEND_URL") {
            config.backendUrl = value;
        } else if (key == "SYSWATCH_AGENT_TOKEN") {
            config.backendToken = value;
        } else if (key == "SYSWATCH_AGENT_ALLOW_INSECURE_PUSH") {
            bool allow = false;
            if (asBool(value, allow)) {
                config.allowInsecurePush = allow;
            } else {
                result.problems.push_back(key + " must be true or false");
            }
        } else if (key == "SYSWATCH_AGENT_LOG_FILE") {
            config.logPath = value;
        } else if (key == "SYSWATCH_AGENT_PORT") {
            // The port, and only the port. There is no key for the bind
            // address, here or anywhere: the agent serves every metric it
            // collects with no authentication, and 127.0.0.1 is what makes
            // that safe. See HTTPServer::start().
            long long number = 0;
            if (asLong(value, number) && number > 0 && number <= 65535) {
                config.serverPort = static_cast<unsigned short>(number);
            } else {
                result.problems.push_back(key + " must be a port between 1 and 65535");
            }
        } else if (key == "SYSWATCH_AGENT_INTERVAL_SECONDS") {
            long long number = 0;
            if (asLong(value, number) && number > 0 && number <= 3600) {
                config.collectionInterval = std::chrono::seconds(number);
            } else {
                result.problems.push_back(
                    key + " must be a whole number of seconds between 1 and 3600");
            }
        } else if (key == "SYSWATCH_AGENT_PUSH_TIMEOUT_SECONDS") {
            long long number = 0;
            if (asLong(value, number) && number > 0 && number <= 300) {
                config.pushTimeoutMs = static_cast<int>(number * 1000);
            } else {
                result.problems.push_back(
                    key + " must be a whole number of seconds between 1 and 300");
            }
        } else if (key == "SYSWATCH_AGENT_PUSH_BUFFER") {
            long long number = 0;
            if (asLong(value, number) && number > 0 && number <= 100000) {
                config.pushBufferSize = static_cast<std::size_t>(number);
            } else {
                result.problems.push_back(key + " must be a count between 1 and 100000");
            }
        }
    }

    return result;
}

} // namespace config
