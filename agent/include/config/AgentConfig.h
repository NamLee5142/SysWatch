#pragma once

#include <chrono>
#include <cstdlib>
#include <string>

namespace agent {

// %PROGRAMDATA%\SysWatch\logs\agent.log, beside the backend's logs, falling
// back to a relative path where that variable does not exist.
inline std::string defaultLogPath() {
#if defined(_WIN32)
    if (const char *programData = std::getenv("PROGRAMDATA")) {
        return std::string(programData) + R"(\SysWatch\logs\agent.log)";
    }
#endif
    return "logs/agent.log";
}

struct AgentConfig {
    std::chrono::milliseconds collectionInterval{std::chrono::seconds(1)};
    // Port only — there is deliberately no bind-host field. HTTPServer always
    // binds 127.0.0.1, because the agent serves every collected metric with no
    // authentication of its own; SysWatch authenticates at the backend instead.
    // A configurable host would be a footgun whose only new setting is the one
    // that publishes the machine's telemetry to the network. See the comment in
    // HTTPServer::start() and http_server_bind_tests.cpp.
    unsigned short serverPort{8080};
    // Absolute, and next to the backend's logs rather than relative to the
    // working directory: a Windows Service starts in C:\Windows\System32, so a
    // relative path would either fail on permissions or leave a log somewhere
    // nobody thinks to look. Empty disables file logging.
    std::string logPath{defaultLogPath()};

    // Where to push snapshots, and what to present when doing it.
    //
    // Empty by default, and empty means exactly what the agent did before this
    // existed: collect, serve on loopback, push nothing. That is the common
    // case - one machine, monitoring itself, with a backend beside it that
    // polls - and it must keep working with no configuration at all.
    //
    // Both are needed together. A URL with no token would be refused by the
    // backend on every push; a token with no URL has nowhere to go. Whichever
    // is set alone is a half-finished configuration and is reported as one.
    std::string backendUrl;
    std::string backendToken;

    // Per push. Ten seconds matches the backend's own outbound timeouts, and
    // the reason for a limit at all is that the push runs on the collection
    // thread: an unreachable backend delays the next collection by whatever
    // this is.
    int pushTimeoutMs{10000};

    bool pushesToABackend() const { return !backendUrl.empty(); }
};

} // namespace agent
