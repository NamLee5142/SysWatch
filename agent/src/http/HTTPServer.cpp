#include "http/HTTPServer.h"
#include <chrono>
#include <cstring>
#include <system_error>

namespace http {

HTTPServer::HTTPServer(agent::Agent &agent)
    : agent_(agent), port_(agent::AgentConfig().serverPort) {
#if defined(_WIN32)
    listenSocket_ = INVALID_SOCKET;
#else
    listenSocket_ = -1;
#endif
}

HTTPServer::HTTPServer(agent::Agent &agent, unsigned short port)
    : agent_(agent), port_(port) {
#if defined(_WIN32)
    listenSocket_ = INVALID_SOCKET;
#else
    listenSocket_ = -1;
#endif
}

HTTPServer::~HTTPServer() {
    stop();
}

void HTTPServer::start() {
    if (running_.load()) return;

#if defined(_WIN32)
    WSADATA wsaData;
    if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) {
        return;
    }
    winsockStarted_ = true;
#endif

    // create socket
#if defined(_WIN32)
    listenSocket_ = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
#else
    listenSocket_ = socket(AF_INET, SOCK_STREAM, 0);
#endif
    if (listenSocket_ == -1 || listenSocket_ == INVALID_SOCKET) {
        return;
    }

    int opt = 1;
#if defined(_WIN32)
    setsockopt(listenSocket_, SOL_SOCKET, SO_REUSEADDR, (const char *)&opt, sizeof(opt));
#else
    setsockopt(listenSocket_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#endif

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port_);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    if (bind(listenSocket_, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) != 0) {
        // cleanup
#if defined(_WIN32)
        closesocket(listenSocket_);
#else
        close(listenSocket_);
#endif
        listenSocket_ = -1;
#if defined(_WIN32)
        if (winsockStarted_) WSACleanup();
        winsockStarted_ = false;
#endif
        return;
    }

    if (listen(listenSocket_, SOMAXCONN) != 0) {
        // cleanup
#if defined(_WIN32)
        closesocket(listenSocket_);
#else
        close(listenSocket_);
#endif
        listenSocket_ = -1;
#if defined(_WIN32)
        if (winsockStarted_) WSACleanup();
        winsockStarted_ = false;
#endif
        return;
    }

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

    if (listenSocket_ != -1 && listenSocket_ != INVALID_SOCKET) {
#if defined(_WIN32)
        closesocket(listenSocket_);
#else
        close(listenSocket_);
#endif
        listenSocket_ = -1;
    }

#if defined(_WIN32)
    if (winsockStarted_) {
        WSACleanup();
        winsockStarted_ = false;
    }
#endif
}

} // namespace http
