// The agent has no authentication. It hands every collected metric to anyone
// who can open a socket to it, and it never will authenticate — Sprint 9 put
// authentication at the backend boundary instead, on the deliberate assumption
// that the agent is reachable only from its own host.
//
// The loopback bind in HTTPServer::start() is the whole of that assumption.
// Changing it to INADDR_ANY / "0.0.0.0" would publish CPU, memory, disk,
// process and network detail to the local network and route straight past the
// backend's login. This test fails if that ever happens.

#include "http/HTTPServer.h"
#include "agent/Agent.h"
#include <cassert>
#include <chrono>
#include <cstring>
#include <iostream>
#include <thread>
#include <vector>

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
using SockLen = int;
#else
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
using SockLen = socklen_t;
#define INVALID_SOCKET (-1)
#endif

namespace {

constexpr unsigned short TestPort = 54329;
constexpr int ConnectTimeoutMs = 1000;

void closeSocket(SocketHandle socketHandle) {
#if defined(_WIN32)
    closesocket(socketHandle);
#else
    close(socketHandle);
#endif
}

bool setNonBlocking(SocketHandle socketHandle) {
#if defined(_WIN32)
    u_long mode = 1;
    return ioctlsocket(socketHandle, FIONBIO, &mode) == 0;
#else
    int flags = fcntl(socketHandle, F_GETFL, 0);
    return flags != -1 && fcntl(socketHandle, F_SETFL, flags | O_NONBLOCK) == 0;
#endif
}

bool connectIsPending() {
#if defined(_WIN32)
    return WSAGetLastError() == WSAEWOULDBLOCK;
#else
    return errno == EINPROGRESS;
#endif
}

// Non-blocking so a firewall that drops packets times out instead of hanging
// the test. A timeout counts as "not reachable", which is what is being
// asserted — refused and filtered are equally fine here.
bool canConnect(in_addr target, unsigned short port, int timeoutMs) {
    SocketHandle clientSocket = socket(AF_INET, SOCK_STREAM, 0);
    if (clientSocket == INVALID_SOCKET) {
        return false;
    }

    if (!setNonBlocking(clientSocket)) {
        closeSocket(clientSocket);
        return false;
    }

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr = target;

    bool connected = false;
    if (connect(clientSocket, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) == 0) {
        connected = true;
    } else if (connectIsPending()) {
        fd_set writable;
        FD_ZERO(&writable);
        FD_SET(clientSocket, &writable);

        timeval timeout{};
        timeout.tv_sec = timeoutMs / 1000;
        timeout.tv_usec = (timeoutMs % 1000) * 1000;

        if (select(static_cast<int>(clientSocket) + 1, nullptr, &writable, nullptr, &timeout) > 0) {
            int socketError = 0;
            SockLen length = sizeof(socketError);
            if (getsockopt(clientSocket, SOL_SOCKET, SO_ERROR,
                           reinterpret_cast<char *>(&socketError), &length) == 0) {
                connected = socketError == 0;
            }
        }
    }

    closeSocket(clientSocket);
    return connected;
}

bool isLoopback(in_addr address) {
    return (ntohl(address.s_addr) >> 24) == 127;
}

std::string describe(in_addr address) {
    char text[INET_ADDRSTRLEN]{};
    inet_ntop(AF_INET, &address, text, sizeof(text));
    return text;
}

// Every IPv4 address this host answers to under its own name, minus loopback.
// These are the addresses a machine on the same network would use, so they are
// exactly what must not reach the agent.
std::vector<in_addr> nonLoopbackAddresses() {
    std::vector<in_addr> addresses;

    char hostname[256]{};
    if (gethostname(hostname, sizeof(hostname) - 1) != 0) {
        return addresses;
    }

    addrinfo hints{};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;

    addrinfo *results = nullptr;
    if (getaddrinfo(hostname, nullptr, &hints, &results) != 0) {
        return addresses;
    }

    for (addrinfo *entry = results; entry != nullptr; entry = entry->ai_next) {
        auto *ipv4 = reinterpret_cast<sockaddr_in *>(entry->ai_addr);
        if (!isLoopback(ipv4->sin_addr)) {
            addresses.push_back(ipv4->sin_addr);
        }
    }

    freeaddrinfo(results);
    return addresses;
}

} // namespace

int main() {
#if defined(_WIN32)
    WSADATA wsaData;
    if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) {
        std::cerr << "WSAStartup failed." << std::endl;
        return 1;
    }
#endif

    agent::Agent agent;
    http::HTTPServer server(agent, TestPort);

    server.start();
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    in_addr loopback{};
    inet_pton(AF_INET, "127.0.0.1", &loopback);

    // The backend's only route in. If this fails the server is not listening at
    // all and the rest of the test would pass for the wrong reason.
    assert(canConnect(loopback, TestPort, ConnectTimeoutMs));

    int failures = 0;
    const std::vector<in_addr> external = nonLoopbackAddresses();

    if (external.empty()) {
        std::cout << "No non-loopback IPv4 address on this host; "
                  << "the exposure check could not run." << std::endl;
    }

    for (const in_addr &address : external) {
        if (canConnect(address, TestPort, ConnectTimeoutMs)) {
            std::cerr << "FAIL: agent is reachable on " << describe(address)
                      << " — the HTTP server must bind 127.0.0.1 only." << std::endl;
            ++failures;
        } else {
            std::cout << "Not reachable on " << describe(address) << " (expected)." << std::endl;
        }
    }

    server.stop();

#if defined(_WIN32)
    WSACleanup();
#endif

    if (failures > 0) {
        return 1;
    }

    std::cout << "HTTPServer loopback bind test passed." << std::endl;
    return 0;
}
