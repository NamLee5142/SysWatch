#pragma once

#include "agent/Agent.h"
#include <thread>
#include <atomic>

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
using SocketHandle = SOCKET;
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
using SocketHandle = int;
#endif

namespace http {

class HTTPServer {
public:
    explicit HTTPServer(agent::Agent &agent);
    explicit HTTPServer(agent::Agent &agent, unsigned short port);
    ~HTTPServer();

    void start();
    void stop();

private:
    agent::Agent &agent_;
    std::thread serverThread_;
    std::atomic<bool> running_{false};
    unsigned short port_{8080};
    SocketHandle listenSocket_;
    bool winsockStarted_{false};
    static constexpr unsigned short DefaultPort = 8080;

    void cleanupSocket();
    void acceptLoop();
    void handleClient(SocketHandle clientSocket);
};

} // namespace http
