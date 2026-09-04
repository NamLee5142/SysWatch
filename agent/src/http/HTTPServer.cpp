#include "http/HTTPServer.h"
#include "http/HttpParser.h"
#include "http/HttpResponse.h"
#include <chrono>
#include <cstring>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>

namespace http {

namespace {

std::string quoteJsonString(const std::string &value) {
    std::ostringstream out;
    out << '"';
    for (char c : value) {
        switch (c) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\b': out << "\\b"; break;
            case '\f': out << "\\f"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    out << "\\u" << std::hex << std::uppercase << std::setw(4) << std::setfill('0') << (int)c;
                } else {
                    out << c;
                }
                break;
        }
    }
    out << '"';
    return out.str();
}

// Renders a time point as ISO-8601 in UTC, e.g. 2026-08-12T11:15:27Z.
std::string formatIso8601Utc(std::chrono::system_clock::time_point when) {
    const std::time_t seconds = std::chrono::system_clock::to_time_t(when);

    std::tm utc{};
#if defined(_WIN32)
    gmtime_s(&utc, &seconds);
#else
    gmtime_r(&seconds, &utc);
#endif

    std::ostringstream out;
    out << std::put_time(&utc, "%Y-%m-%dT%H:%M:%SZ");
    return out.str();
}

std::string jsonFor(const CPUInfo &cpu) {
    std::ostringstream out;
    out << "{"
        << "\"coreCount\":" << cpu.coreCount << ","
        << "\"usagePercent\":" << cpu.usagePercent
        << "}";
    return out.str();
}

std::string jsonFor(const MemoryInfo &memory) {
    std::ostringstream out;
    out << "{"
        << "\"totalMB\":" << memory.totalMB << ","
        << "\"usedMB\":" << memory.usedMB
        << "}";
    return out.str();
}

std::string jsonFor(const DiskInfo &disk) {
    std::ostringstream out;
    out << "{"
        << "\"totalGB\":" << disk.totalGB << ","
        << "\"freeGB\":" << disk.freeGB
        << "}";
    return out.str();
}

std::string jsonFor(const SystemInfo &system) {
    std::ostringstream out;
    out << "{"
        << "\"name\":" << quoteJsonString(system.name) << ","
        << "\"version\":" << quoteJsonString(system.version) << ","
        << "\"hostName\":" << quoteJsonString(system.hostName)
        << "}";
    return out.str();
}

std::string jsonFor(const ProcessEntry &process) {
    std::ostringstream out;
    out << "{"
        << "\"pid\":" << process.pid << ","
        << "\"name\":" << quoteJsonString(process.name) << ","
        << "\"memoryMB\":" << process.memoryMB
        << "}";
    return out.str();
}

std::string jsonFor(const NetworkInterfaceInfo &nic) {
    std::ostringstream out;
    out << "{"
        << "\"name\":" << quoteJsonString(nic.name) << ","
        << "\"bytesSent\":" << nic.bytesSent << ","
        << "\"bytesRecv\":" << nic.bytesRecv << ","
        << "\"bytesSentPerSec\":" << nic.bytesSentPerSec << ","
        << "\"bytesRecvPerSec\":" << nic.bytesRecvPerSec
        << "}";
    return out.str();
}

// The snapshot emitter had only object serializers; a process list and an
// interface list are the first arrays on the wire.
template <typename T>
std::string jsonArray(const std::vector<T> &items) {
    std::ostringstream out;
    out << '[';
    for (std::size_t i = 0; i < items.size(); ++i) {
        if (i != 0) {
            out << ',';
        }
        out << jsonFor(items[i]);
    }
    out << ']';
    return out.str();
}

std::string jsonFor(const ProcessInfo &processes) {
    std::ostringstream out;
    out << "{"
        << "\"count\":" << processes.count << ","
        << "\"top\":" << jsonArray(processes.top)
        << "}";
    return out.str();
}

std::string jsonFor(const NetworkInfo &network) {
    std::ostringstream out;
    out << "{"
        << "\"interfaces\":" << jsonArray(network.interfaces)
        << "}";
    return out.str();
}

std::string snapshotToJson(const Snapshot &snapshot) {
    std::ostringstream out;
    out << "{"
        << "\"collectedAt\":" << quoteJsonString(formatIso8601Utc(snapshot.collectedAt)) << ","
        << "\"cpuInfo\":" << jsonFor(snapshot.cpuInfo) << ","
        << "\"memoryInfo\":" << jsonFor(snapshot.memoryInfo) << ","
        << "\"diskInfo\":" << jsonFor(snapshot.diskInfo) << ","
        << "\"systemInfo\":" << jsonFor(snapshot.systemInfo) << ","
        << "\"processInfo\":" << jsonFor(snapshot.processInfo) << ","
        << "\"networkInfo\":" << jsonFor(snapshot.networkInfo)
        << "}";
    return out.str();
}

std::string buildHttpResponseString(const HttpResponse &response) {
    std::ostringstream out;
    out << "HTTP/1.1 " << response.status << " ";
    switch (response.status) {
        case 200:
            out << "OK";
            break;
        case 204:
            out << "No Content";
            break;
        case 404:
            out << "Not Found";
            break;
        case 400:
            out << "Bad Request";
            break;
        default:
            out << "Status";
            break;
    }
    out << "\r\n";

    if (response.headers.find("Content-Length") == response.headers.end()) {
        out << "Content-Length: " << response.body.size() << "\r\n";
    }

    for (const auto &header : response.headers) {
        out << header.first << ": " << header.second << "\r\n";
    }

    out << "\r\n";
    out << response.body;
    return out.str();
}

bool sendAll(SocketHandle socket, const char *data, size_t size) {
    size_t totalSent = 0;
    while (totalSent < size) {
        int sent = static_cast<int>(send(socket, data + totalSent, static_cast<int>(size - totalSent), 0));
        if (sent <= 0) {
            return false;
        }
        totalSent += static_cast<size_t>(sent);
    }
    return true;
}

HttpResponse routeRequest(const HttpRequest &request, const agent::Agent &agent) {
    HttpResponse response;
    if (request.method == "GET" && request.path == "/snapshot") {
        auto snapshot = agent.latestSnapshot();
        if (snapshot) {
            response.status = 200;
            response.headers["Content-Type"] = "application/json";
            response.body = snapshotToJson(*snapshot);
        } else {
            response.status = 204;
            response.headers["Content-Type"] = "text/plain";
            response.body = "";
        }
    } else {
        response.status = 404;
        response.headers["Content-Type"] = "text/plain";
        response.body = "Not Found";
    }
    return response;
}

} // namespace

HTTPServer::HTTPServer(agent::Agent &agent)
    : HTTPServer(agent, DefaultPort) {}

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
        cleanupSocket();
        return;
    }

    int opt = 1;
#if defined(_WIN32)
    // SO_EXCLUSIVEADDRUSE, not SO_REUSEADDR. Windows lets a second socket bind
    // an address another socket is already listening on when SO_REUSEADDR is
    // set — two agents then both appear to start, requests land on whichever
    // the OS picks, and nothing anywhere reports a problem. This is what makes
    // the "could not listen" path in AgentRuntime reachable at all.
    setsockopt(listenSocket_, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, (const char *)&opt, sizeof(opt));
#else
    // On POSIX the same option means the harmless thing: rebind after a
    // previous listener's TIME_WAIT rather than steal a live one.
    setsockopt(listenSocket_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#endif

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port_);
    // Loopback only, and deliberately not configurable. This server has no
    // authentication and will not grow any: SysWatch puts login at the backend
    // boundary instead, on the assumption that the agent is reachable from its
    // own host and nowhere else. Binding INADDR_ANY here would publish every
    // collected metric to the local network and route straight past that login.
    // http_server_bind_tests.cpp fails if this changes.
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    if (bind(listenSocket_, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) != 0) {
        cleanupSocket();
        return;
    }

    if (listen(listenSocket_, SOMAXCONN) != 0) {
        cleanupSocket();
        return;
    }

    // make running_ transition atomic and avoid races
    if (running_.exchange(true)) {
        // already running; cleanup this socket
        cleanupSocket();
        return;
    }

    serverThread_ = std::thread(&HTTPServer::acceptLoop, this);
}

void HTTPServer::stop() {
    if (!running_.exchange(false)) return;

    cleanupSocket();

    if (serverThread_.joinable()) serverThread_.join();
}

void HTTPServer::cleanupSocket() {
    if (listenSocket_ != -1 && listenSocket_ != INVALID_SOCKET) {
#if defined(_WIN32)
        closesocket(listenSocket_);
#else
        close(listenSocket_);
#endif
        listenSocket_ =
#if defined(_WIN32)
            INVALID_SOCKET
#else
            -1
#endif
            ;
    }

#if defined(_WIN32)
    if (winsockStarted_) {
        WSACleanup();
        winsockStarted_ = false;
    }
#endif
}

void HTTPServer::acceptLoop() {
    while (running_.load()) {
        SocketHandle clientSocket = accept(listenSocket_, nullptr, nullptr);
        if (clientSocket == -1 || clientSocket == INVALID_SOCKET) {
            if (!running_.load()) {
                break;
            }
            continue;
        }

        handleClient(clientSocket);
    }
}

void HTTPServer::handleClient(SocketHandle clientSocket) {
    std::vector<char> buffer(4096);
    std::string rawRequest;

    while (running_.load()) {
        int bytesRead = recv(clientSocket, buffer.data(), static_cast<int>(buffer.size()), 0);
        if (bytesRead <= 0) {
            break;
        }

        rawRequest.append(buffer.data(), bytesRead);
        if (rawRequest.find("\r\n\r\n") != std::string::npos) {
            break;
        }
    }

    http::HttpRequest request;
    http::HttpResponse response;

    if (parseHttpRequest(rawRequest, request)) {
        response = routeRequest(request, agent_);
    } else {
        response.status = 400;
        response.headers["Content-Type"] = "text/plain";
        response.body = "Bad Request";
    }

    std::string responseText = buildHttpResponseString(response);
    sendAll(clientSocket, responseText.c_str(), responseText.size());

#if defined(_WIN32)
    closesocket(clientSocket);
#else
    close(clientSocket);
#endif
}

} // namespace http
