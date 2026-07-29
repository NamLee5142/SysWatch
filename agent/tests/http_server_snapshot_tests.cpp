#include "http/HTTPServer.h"
#include "agent/Agent.h"
#include "collector/SnapshotCollector.h"
#include <cassert>
#include <chrono>
#include <cstring>
#include <iostream>
#include <string>
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

static bool sendRequest(const std::string &request, std::string &response, unsigned short port) {
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
    if (!connected) {
#if defined(_WIN32)
        closesocket(clientSocket);
        WSACleanup();
#else
        close(clientSocket);
#endif
        return false;
    }

    send(clientSocket, request.c_str(), static_cast<int>(request.size()), 0);

    char buffer[4096];
    int bytesRead = recv(clientSocket, buffer, sizeof(buffer) - 1, 0);
    if (bytesRead <= 0) {
#if defined(_WIN32)
        closesocket(clientSocket);
        WSACleanup();
#else
        close(clientSocket);
#endif
        return false;
    }

    buffer[bytesRead] = '\0';
    response.assign(buffer, bytesRead);

#if defined(_WIN32)
    closesocket(clientSocket);
    WSACleanup();
#else
    close(clientSocket);
#endif

    return true;
}

int main() {
    agent::Agent agent;
    unsigned short port = 54323;
    http::HTTPServer server(agent, port);

    server.start();
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    std::string response;
    bool ok = sendRequest("GET /snapshot HTTP/1.1\r\nHost: localhost\r\n\r\n", response, port);
    assert(ok);
    assert(response.find("204 No Content") != std::string::npos);

    server.stop();
    std::cout << "HTTPServer snapshot no-content test passed." << std::endl;
    return 0;
}
