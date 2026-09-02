#include "http/HTTPServer.h"
#include "agent/Agent.h"
#include "collector/SnapshotCollector.h"
#include <cassert>
#include <cctype>
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

// Reads the value of a top-level JSON string field out of a response body.
static bool readJsonString(const std::string &body, const std::string &key, std::string &value) {
    const std::string marker = "\"" + key + "\":\"";
    const size_t start = body.find(marker);
    if (start == std::string::npos) {
        return false;
    }

    const size_t valueStart = start + marker.size();
    const size_t valueEnd = body.find('"', valueStart);
    if (valueEnd == std::string::npos) {
        return false;
    }

    value = body.substr(valueStart, valueEnd - valueStart);
    return true;
}

// Matches the ISO-8601 UTC shape the backend will parse, e.g. 2026-08-12T11:15:27Z.
static bool isIso8601Utc(const std::string &value) {
    const std::string shape = "0000-00-00T00:00:00Z"; // '0' stands for any digit
    if (value.size() != shape.size()) {
        return false;
    }

    for (size_t i = 0; i < shape.size(); ++i) {
        if (shape[i] == '0') {
            if (!std::isdigit(static_cast<unsigned char>(value[i]))) {
                return false;
            }
        } else if (value[i] != shape[i]) {
            return false;
        }
    }
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

    // Once the agent has collected, the payload carries a usable collection time.
    agent.start();
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    response.clear();
    ok = sendRequest("GET /snapshot HTTP/1.1\r\nHost: localhost\r\n\r\n", response, port);
    assert(ok);
    assert(response.find("200 OK") != std::string::npos);

    std::string collectedAt;
    assert(readJsonString(response, "collectedAt", collectedAt));
    assert(isIso8601Utc(collectedAt));

    // A default-constructed time point would serialize as the epoch, which would
    // mean the collector never stamped the snapshot.
    assert(collectedAt.rfind("1970-", 0) != 0);

    // Sprint 7: the payload now carries a process block (an object with a count
    // and a top array) and a network block (an object holding an interfaces
    // array). The array serializer is new — nothing else on the wire uses one.
    const size_t processAt = response.find("\"processInfo\":{");
    assert(processAt != std::string::npos);
    assert(response.find("\"count\":", processAt) != std::string::npos);
    assert(response.find("\"top\":[", processAt) != std::string::npos);

    assert(response.find("\"networkInfo\":{\"interfaces\":[") != std::string::npos);

    // The real collector runs on a Windows host here, so there is at least one
    // process, and its top entry is a fully formed object.
    assert(response.find("\"pid\":", processAt) != std::string::npos);
    assert(response.find("\"memoryMB\":", processAt) != std::string::npos);

    // With ten entries the array serializer's separator has to fire: adjacent
    // objects are joined by "},{" and nothing trails the last one.
    assert(response.find("},{", processAt) != std::string::npos);
    assert(response.find(",]") == std::string::npos);

    agent.stop();
    server.stop();
    std::cout << "HTTPServer snapshot test passed. collectedAt=" << collectedAt << std::endl;
    return 0;
}
