#include "runtime/AgentRuntime.h"

#include <chrono>
#include <thread>
#include "http/HTTPServer.h"

namespace runtime {

namespace {

// How often the wait loop checks the stop flag. Short enough that a stop feels
// immediate, long enough that an idle agent is not spinning.
constexpr std::chrono::milliseconds PollInterval{200};

} // namespace

int runUntilStopped(const agent::AgentConfig &config,
                    const std::function<bool()> &shouldStop,
                    Callbacks callbacks) {
    agent::Agent agent(config, callbacks.onSnapshot);
    http::HTTPServer server(agent, config.serverPort);

    server.start();
    agent.start();

    if (callbacks.onReady) {
        callbacks.onReady();
    }

    while (!shouldStop()) {
        std::this_thread::sleep_for(PollInterval);
    }

    agent.stop();
    server.stop();

    return 0;
}

} // namespace runtime
