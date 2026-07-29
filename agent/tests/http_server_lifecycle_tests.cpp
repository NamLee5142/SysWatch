#include "http/HTTPServer.h"
#include "agent/Agent.h"
#include <cassert>
#include <iostream>

int main() {
    try {
        std::cout << "http_test: before Agent construction" << std::endl;
        agent::Agent agent;
        std::cout << "http_test: after Agent construction" << std::endl;

        http::HTTPServer server(agent);
        std::cout << "http_test: after HTTPServer construction" << std::endl;

        // stop before start is safe
        server.stop();
        std::cout << "http_test: after stop() before start" << std::endl;

        // start once
        server.start();
        std::cout << "http_test: after first start()" << std::endl;

        // start again should be safe (no double-start)
        server.start();
        std::cout << "http_test: after second start()" << std::endl;

        // stop twice should be safe
        server.stop();
        std::cout << "http_test: after first stop()" << std::endl;
        server.stop();
        std::cout << "http_test: after second stop()" << std::endl;

        std::cout << "HTTPServer lifecycle test passed." << std::endl;
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "http_test: caught std::exception: " << e.what() << std::endl;
        assert(false && "Constructing HTTPServer should not throw");
        return 1;
    } catch (...) {
        std::cerr << "http_test: caught unknown exception" << std::endl;
        assert(false && "Constructing HTTPServer should not throw");
        return 1;
    }
}
