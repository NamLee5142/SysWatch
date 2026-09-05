#include "runtime/AgentRuntime.h"

#include <chrono>
#include <thread>
#include "http/HTTPServer.h"
#include "logging/Logger.h"

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

    agent::Agent agent(config, callbacks.onSnapshot);
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
