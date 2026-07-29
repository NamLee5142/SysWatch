#include "http/HTTPServer.h"
#include <chrono>

namespace http {

HTTPServer::HTTPServer(agent::Agent &agent)
    : agent_(agent) {}

HTTPServer::~HTTPServer() {
    stop();
}

void HTTPServer::start() {
    if (running_.load()) return;
    running_.store(true);
    serverThread_ = std::thread([this]() {
        while (running_.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    });
}

void HTTPServer::stop() {
    if (!running_.load()) return;
    running_.store(false);
    if (serverThread_.joinable()) serverThread_.join();
}

} // namespace http
