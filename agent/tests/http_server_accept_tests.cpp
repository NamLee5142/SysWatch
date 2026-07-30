#include "http/HTTPServer.h"
#include "agent/Agent.h"
#include <cassert>
#include <chrono>
#include <iostream>
#include <thread>

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
using SocketHandle = SOCKET;
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
using SocketHandle = int;
#endif

static bool connectToLocalhost(unsigned short port) {
#if defined(_WIN32)
    WSADATA wsaData;
    if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) {
        return false;
    }
#endif

    SocketHandle clientSocket = socket(AF_INET, SOCK_STREAM, 0);
    if (clientSocket == -1 || clientSocket == INVALID_SOCKET) {
#if defined(_WIN32)
        WSACleanup();
#endif
        return false;
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    bool connected = connect(clientSocket, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) == 0;

    if (clientSocket != -1 && clientSocket != INVALID_SOCKET) {
#if defined(_WIN32)
        closesocket(clientSocket);
#else
        close(clientSocket);
#endif
    }

#if defined(_WIN32)
    WSACleanup();
#endif

    return connected;
}

int main() {
    agent::Agent agent;
    unsigned short port = 54321;
    http::HTTPServer server(agent, port);

    server.start();
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    assert(connectToLocalhost(port));

    server.stop();

    std::cout << "HTTPServer accept test passed." << std::endl;
    return 0;
}
