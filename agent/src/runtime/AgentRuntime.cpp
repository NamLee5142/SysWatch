#include "runtime/AgentRuntime.h"

#include <chrono>
#include <memory>
#include <thread>
#include "http/HTTPServer.h"
#include "http/Url.h"
#include "logging/Logger.h"
#include "push/SnapshotPusher.h"

namespace runtime {

namespace {

// How often the wait loop checks the stop flag. Short enough that a stop feels
// immediate, long enough that an idle agent is not spinning.
constexpr std::chrono::milliseconds PollInterval{200};

constexpr int ExitBindFailed = 1;

// How many consecutive failures before the log stops repeating itself. A
// backend that has been down for a day should not have written 86,400 lines
// saying so; the poller on the other side thins out the same way.
constexpr int FailuresBeforeQuieting = 5;

} // namespace

int runUntilStopped(const agent::AgentConfig &config,
                    const std::function<bool()> &shouldStop,
                    Callbacks callbacks) {
    logging::Logger log(config.logPath);

    // SYSWATCH_VERSION comes from the VERSION file by way of CMake, so a log
    // from a machine in the field names the build that wrote it.
    log.info(std::string("Agent starting, version ") + SYSWATCH_VERSION);
    if (!log.writingToFile() && !config.logPath.empty()) {
        log.warning("No log file; running with console output only");
    }

    // Chained in front of whatever the caller asked for, rather than replacing
    // it: the console entry point still prints, and a pushing agent still
    // serves loopback. Push is an addition to what the agent does, not a mode
    // it switches into.
    agent::Agent::SnapshotHandler onSnapshot = callbacks.onSnapshot;

    std::unique_ptr<push::SnapshotPusher> pusher;
    if (config.pushesToABackend()) {
        http::Url destination;
        if (!http::Url::parse(config.backendUrl, destination)) {
            log.error("Backend URL could not be parsed: " + config.backendUrl +
                      " - expected something like http://backend:8000/api/ingest/snapshot");
            return ExitBadConfiguration;
        }

        if (config.backendToken.empty()) {
            // Refused rather than attempted. Every push would come back 401,
            // and the agent would look like it was working.
            log.error("A backend URL is configured but no token is. "
                      "Issue one with 'python -m app.auth.create_agent_token "
                      "--host <name>' on the backend.");
            return ExitBadConfiguration;
        }

        pusher = std::make_unique<push::SnapshotPusher>(destination, config.backendToken,
                                                        config.pushTimeoutMs);

        auto failures = std::make_shared<int>(0);
        auto previous = onSnapshot;
        onSnapshot = [&log, &pusher, failures, previous](const Snapshot &snapshot) {
            if (previous) {
                previous(snapshot);
            }

            const auto outcome = pusher->push(snapshot);

            if (outcome.delivered) {
                if (*failures > 0) {
                    log.info("Pushing to the backend again after " +
                             std::to_string(*failures) + " failed attempts");
                    *failures = 0;
                }
                return;
            }

            ++*failures;
            // A refusal is always logged: it does not fix itself, and the
            // machine looks healthy while nothing arrives.
            if (outcome.refused || *failures <= FailuresBeforeQuieting) {
                log.warning("Could not push a snapshot (" +
                            std::to_string(*failures) + " in a row): " + outcome.detail);
            } else if (*failures == FailuresBeforeQuieting + 1) {
                log.warning("Still cannot push to the backend; saying so once an hour "
                            "from here rather than on every collection");
            }
        };
    } else if (!config.backendToken.empty()) {
        log.warning("A backend token is configured but no URL is, so nothing is "
                    "pushed. Set the backend URL, or remove the token.");
    }

    agent::Agent agent(config, onSnapshot);
    http::HTTPServer server(agent, config.serverPort);

    server.start();

    if (!server.isRunning()) {
        // Almost always the port already being in use. Before this the agent
        // came up, listened to nothing and reported nothing, so the only
        // symptom was a backend that never collected.
        log.error("Could not listen on 127.0.0.1:" + std::to_string(config.serverPort) +
                  " — is another agent already running?");
        return ExitBindFailed;
    }

    log.info("Listening on 127.0.0.1:" + std::to_string(config.serverPort));

    agent.start();
    log.info("Collecting every " + std::to_string(config.collectionInterval.count()) + "ms");

    if (pusher) {
        // The destination, never the token.
        log.info("Pushing snapshots to " + config.backendUrl);
    }

    if (callbacks.onReady) {
        callbacks.onReady();
    }

    while (!shouldStop()) {
        std::this_thread::sleep_for(PollInterval);
    }

    log.info("Agent stopping");

    agent.stop();
    server.stop();

    log.info("Agent stopped");
    return 0;
}

} // namespace runtime
