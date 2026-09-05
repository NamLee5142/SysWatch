#include "http/HTTPServer.h"
#include "agent/Agent.h"
#include <cassert>
#include <iostream>

namespace {

// Its own port, like every other socket test. The default 8080 belongs to a
// real agent, and since the server took SO_EXCLUSIVEADDRUSE this test fails
// outright whenever one happens to be running — including the service, on the
// machine most likely to be running CI.
constexpr unsigned short TestPort = 54326;

} // namespace

int main() {
    try {
        agent::Agent agent;
        http::HTTPServer server(agent, TestPort);

        // stop before start is safe
        server.stop();

        // start once
        server.start();

        // start again should be safe (no double-start)
        server.start();

        // stop twice should be safe
        server.stop();
        server.stop();

        // destructor stops running thread when leaving scope
        {
            http::HTTPServer scopedServer(agent, TestPort);
            scopedServer.start();
        }

        std::cout << "HTTPServer lifecycle test passed." << std::endl;
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "http_test: failure: " << e.what() << std::endl;
        return EXIT_FAILURE;
    } catch (...) {
        std::cerr << "http_test: failure: unknown exception" << std::endl;
        return EXIT_FAILURE;
    }
}
