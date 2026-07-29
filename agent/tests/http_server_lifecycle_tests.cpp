#include "http/HTTPServer.h"
#include "agent/Agent.h"
#include <cassert>
#include <iostream>

int main() {
    try {
        agent::Agent agent;
        http::HTTPServer server(agent);

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
            http::HTTPServer scopedServer(agent);
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
