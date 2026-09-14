#include "runtime/AgentRuntime.h"

#include <chrono>
#include <memory>
#include <thread>
#include "http/HTTPServer.h"
#include "http/Url.h"
#include "logging/Logger.h"
#include "push/BufferedPusher.h"
#include "push/SnapshotPusher.h"

namespace runtime {

namespace {

// How often the wait loop checks the stop flag. Short enough that a stop feels
// immediate, long enough that an idle agent is not spinning.
constexpr std::chrono::milliseconds PollInterval{200};

constexpr int ExitBindFailed = 1;

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

    std::unique_ptr<push::BufferedPusher> pusher;
    // Kept out here because the startup banner below reports it, and the parsed
    // URL itself has no business outliving the configuration check.
    bool pushingOffThisMachine = false;
    if (config.pushesToABackend()) {
        http::Url destination;
        if (!http::Url::parse(config.backendUrl, destination)) {
            log.error("Backend URL could not be parsed: " + config.backendUrl +
                      " - expected something like http://backend:8000/api/ingest/snapshot");
            return ExitBadConfiguration;
        }

        if (destination.scheme == "https") {
            // Caught here rather than once per push. The client refuses https,
            // and an agent that starts, reports itself healthy and fails every
            // push with the same message is harder to read than one that will
            // not start.
            log.error("The backend URL is https, which this agent cannot speak. "
                      "Terminate TLS in front of the backend and give the agent "
                      "the http:// address behind it.");
            return ExitBadConfiguration;
        }

        if (!destination.isLoopback() && !config.allowInsecurePush) {
            // The rule this commit exists for. Refusing to start is the point:
            // a warning would be read once, and the token would cross the
            // network on every collection thereafter.
            log.error("Refusing to push to " + config.backendUrl +
                      " over plain HTTP: the agent's token would cross the "
                      "network in clear on every push. Put TLS in front of the "
                      "backend, or set allowInsecurePush if the network between "
                      "these machines is genuinely trusted.");
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

        pushingOffThisMachine = !destination.isLoopback();

        pusher = std::make_unique<push::BufferedPusher>(
            push::SnapshotPusher(destination, config.backendToken, config.pushTimeoutMs),
            [&log](const std::string &message) { log.info(message); },
            [&log](const std::string &message) { log.warning(message); },
            config.pushBufferSize);

        // Chained in front of whatever the caller asked for. offer() copies the
        // snapshot and returns, so collection takes as long as collecting even
        // when the backend has been gone for a week.
        auto previous = onSnapshot;
        auto *queue = pusher.get();
        onSnapshot = [queue, previous](const Snapshot &snapshot) {
            if (previous) {
                previous(snapshot);
            }
            queue->offer(snapshot);
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

    if (pusher) {
        pusher->start();
    }

    agent.start();
    log.info("Collecting every " + std::to_string(config.collectionInterval.count()) + "ms");

    if (pusher) {
        // The destination, never the token.
        log.info("Pushing snapshots to " + config.backendUrl);

        if (pushingOffThisMachine) {
            // Every start, deliberately. A decision taken once, months ago, on
            // a network that has since changed, should keep announcing itself.
            log.warning("This agent's token crosses the network in clear on "
                        "every push, because allowInsecurePush is set and the "
                        "backend is not on this machine.");
        }
    }

    if (callbacks.onReady) {
        callbacks.onReady();
    }

    while (!shouldStop()) {
        std::this_thread::sleep_for(PollInterval);
    }

    log.info("Agent stopping");

    agent.stop();
    // After the agent, so nothing is still being offered, and before the log
    // goes out of scope, because the drain thread writes to it.
    if (pusher) {
        pusher->stop();
        const auto stats = pusher->stats();
        log.info("Pushed " + std::to_string(stats.delivered) + " snapshots, dropped " +
                 std::to_string(stats.dropped) + ", refused " +
                 std::to_string(stats.refused) + ", " + std::to_string(stats.queued) +
                 " still held");
    }
    server.stop();

    log.info("Agent stopped");
    return 0;
}

} // namespace runtime
