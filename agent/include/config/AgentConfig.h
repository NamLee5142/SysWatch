#pragma once

#include <chrono>
#include <cstddef>
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

    // Per push. Ten seconds matches the backend's own outbound timeouts.
    //
    // This no longer bounds a delay to collection: BufferedPusher moved the
    // push onto a thread of its own, so an unreachable backend costs the
    // collection loop nothing. What it bounds is how long the pusher waits on
    // a dead backend before giving up on that attempt and retrying.
    int pushTimeoutMs{10000};

    // Send the token over plain HTTP to somewhere that is not this machine.
    //
    // False, and it stays false unless somebody decides otherwise. A push
    // carries the agent's credential in an Authorization header, and over
    // http:// to another machine that header is readable by anything on the
    // path - and a stolen agent token writes any history it likes for the host
    // it names.
    //
    // It exists because the alternative is worse. The agent speaks no TLS, so
    // without this switch a second machine cannot be monitored at all, and an
    // operator who wants it anyway would reach for something further outside
    // the project's control than a setting with a warning on it. Loopback does
    // not need it: a credential that never leaves the machine cannot be
    // intercepted on the way anywhere.
    //
    // Temporary, with a written end date rather than a good intention:
    // docs/decisions/0002-the-agent-speaks-tls-through-winhttp.md settles that
    // the agent will make its requests through WinHTTP and speak https, and
    // docs/sprint-13.md commit 3 deletes this setting in the sprint that makes
    // it unnecessary. If it is still here after that sprint, something went
    // wrong that is worth asking about.
    bool allowInsecurePush{false};

    // How many snapshots to hold while the backend is unreachable. See
    // BufferedPusher for why this is a count rather than a duration.
    std::size_t pushBufferSize{512};

    bool pushesToABackend() const { return !backendUrl.empty(); }
};

} // namespace agent
