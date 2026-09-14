// Pushing a snapshot to a backend that is not this machine.
//
// The backend here is a socket that answers whatever the case needs. That is
// deliberate: the point is what the *agent* does with each answer, and a real
// backend can only produce a few of them on demand. The real one is exercised
// by hand, and by the install workflow.

#include "domain/Snapshot.h"
#include "http/SnapshotJson.h"
#include "http/Url.h"
#include "push/SnapshotPusher.h"

#include <atomic>
#include <cassert>
#include <chrono>
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
#define INVALID_SOCKET (-1)
#endif

namespace {

constexpr unsigned short Port = 54334;
constexpr unsigned short DeadPort = 54335;

void closeHandle(SocketHandle handle) {
#if defined(_WIN32)
    closesocket(handle);
#else
    ::close(handle);
#endif
}

// Answers one request with a fixed reply, and keeps what it was sent.
class FakeBackend {
public:
    explicit FakeBackend(std::string reply) : reply_(std::move(reply)) {
#if defined(_WIN32)
        WSADATA data;
        WSAStartup(MAKEWORD(2, 2), &data);
#endif
        listen_ = ::socket(AF_INET, SOCK_STREAM, 0);
        int on = 1;
#if defined(_WIN32)
        setsockopt(listen_, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, (const char *)&on, sizeof(on));
#else
        setsockopt(listen_, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on));
#endif
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(Port);
        addr.sin_addr.s_addr = inet_addr("127.0.0.1");
        assert(::bind(listen_, (sockaddr *)&addr, sizeof(addr)) == 0);
        assert(::listen(listen_, 1) == 0);
        thread_ = std::thread([this] { serve(); });
    }

    ~FakeBackend() {
        if (thread_.joinable()) {
            thread_.join();
        }
        closeHandle(listen_);
#if defined(_WIN32)
        WSACleanup();
#endif
    }

    const std::string &received() const { return received_; }

private:
    void serve() {
        SocketHandle client = ::accept(listen_, nullptr, nullptr);
        if (client == INVALID_SOCKET) {
            return;
        }

        char buffer[8192];
        const int read = ::recv(client, buffer, sizeof(buffer), 0);
        if (read > 0) {
            received_.assign(buffer, static_cast<std::size_t>(read));
        }

        ::send(client, reply_.data(), (int)reply_.size(), 0);
        closeHandle(client);
    }

    std::string reply_;
    std::string received_;
    SocketHandle listen_{INVALID_SOCKET};
    std::thread thread_;
};

http::Url at(const std::string &text) {
    http::Url url;
    const bool ok = http::Url::parse(text, url);
    assert(ok);
    return url;
}

std::string destination() {
    return "http://127.0.0.1:" + std::to_string(Port) + "/api/ingest/snapshot";
}

Snapshot aSnapshot() {
    Snapshot snapshot;
    snapshot.collectedAt = std::chrono::system_clock::now();
    snapshot.cpuInfo.coreCount = 8;
    snapshot.cpuInfo.usagePercent = 97.4;
    snapshot.memoryInfo.totalMB = 16384;
    snapshot.memoryInfo.usedMB = 4096;
    snapshot.diskInfo.totalGB = 512;
    snapshot.diskInfo.freeGB = 120;
    snapshot.systemInfo.name = "Windows";
    snapshot.systemInfo.version = "11";
    snapshot.systemInfo.hostName = "buildbox";
    return snapshot;
}

const std::string Token = "a-token-that-must-not-be-logged";

void sendsTheSnapshotAsJsonWithTheToken() {
    FakeBackend backend("HTTP/1.1 202 Accepted\r\nContent-Length: 2\r\n\r\nok");
    const push::SnapshotPusher pusher(at(destination()), Token, 2000);

    const auto outcome = pusher.push(aSnapshot());

    assert(outcome.delivered);
    assert(!outcome.refused);

    const std::string &sent = backend.received();
    assert(sent.rfind("POST /api/ingest/snapshot HTTP/1.1", 0) == 0);
    assert(sent.find("Authorization: Bearer " + Token) != std::string::npos);
    assert(sent.find("Content-Type: application/json") != std::string::npos);

    // The same document the loopback server serves, not a second rendering.
    const Snapshot snapshot = aSnapshot();
    assert(sent.find("\"cpuInfo\"") != std::string::npos);
    assert(sent.find("\"hostName\":\"buildbox\"") != std::string::npos);
    assert(sent.find("\"collectedAt\"") != std::string::npos);
}

void aBackendThatIsNotThereIsNotARefusal() {
    // Worth retrying, and the agent must be able to tell it apart from a "no".
    const push::SnapshotPusher pusher(
        at("http://127.0.0.1:" + std::to_string(DeadPort) + "/x"), Token, 2000);

    const auto outcome = pusher.push(aSnapshot());

    assert(!outcome.delivered);
    assert(!outcome.refused);
    assert(!outcome.detail.empty());
}

void aRevokedTokenIsARefusalAndSaysWhatToDo() {
    FakeBackend backend(
        "HTTP/1.1 401 Unauthorized\r\nContent-Length: 30\r\n\r\n"
        "{\"detail\":\"Not authenticated\"}");
    const push::SnapshotPusher pusher(at(destination()), Token, 2000);

    const auto outcome = pusher.push(aSnapshot());

    assert(!outcome.delivered);
    assert(outcome.refused);
    // Retrying a 401 forever changes nothing. The message names the fix,
    // because from outside the machine this looks like a working agent.
    assert(outcome.detail.find("401") != std::string::npos);
    assert(outcome.detail.find("create_agent_token") != std::string::npos ||
           outcome.detail.find("token") != std::string::npos);
}

void anyOtherRefusalIsReportedWithItsStatus() {
    FakeBackend backend("HTTP/1.1 422 Unprocessable\r\nContent-Length: 0\r\n\r\n");
    const push::SnapshotPusher pusher(at(destination()), Token, 2000);

    const auto outcome = pusher.push(aSnapshot());

    assert(!outcome.delivered);
    assert(outcome.refused);
    assert(outcome.detail.find("422") != std::string::npos);
}

void aDuplicateIsStillADelivery() {
    // The backend answers 202 with stored:false when it already had the
    // reading. Nothing went wrong, and the agent must not retry.
    FakeBackend backend(
        "HTTP/1.1 202 Accepted\r\nContent-Length: 38\r\n\r\n"
        "{\"hostName\":\"buildbox\",\"stored\":false}");
    const push::SnapshotPusher pusher(at(destination()), Token, 2000);

    assert(pusher.push(aSnapshot()).delivered);
}

void theTokenIsNeverInWhatComesBack() {
    FakeBackend backend("HTTP/1.1 500 Server Error\r\nContent-Length: 0\r\n\r\n");
    const push::SnapshotPusher pusher(at(destination()), Token, 2000);

    const auto outcome = pusher.push(aSnapshot());

    assert(outcome.detail.find(Token) == std::string::npos);
}

void theSerialisationIsTheServersOwn() {
    // Not a second implementation that happens to agree today. If this ever
    // fails, one of the two renderings has grown a field the other has not.
    const Snapshot snapshot = aSnapshot();
    FakeBackend backend("HTTP/1.1 202 Accepted\r\nContent-Length: 0\r\n\r\n");
    const push::SnapshotPusher pusher(at(destination()), Token, 2000);

    pusher.push(snapshot);

    const std::string expected = http::snapshotToJson(snapshot);
    const std::string &sent = backend.received();
    const std::size_t bodyStart = sent.find("\r\n\r\n");
    assert(bodyStart != std::string::npos);
    const std::string body = sent.substr(bodyStart + 4);

    // collectedAt is a timestamp taken twice, so compare everything after it.
    assert(body.find("\"cpuInfo\"") != std::string::npos);
    assert(body.substr(body.find("\"cpuInfo\"")) ==
           expected.substr(expected.find("\"cpuInfo\"")));
}

} // namespace

int main() {
    sendsTheSnapshotAsJsonWithTheToken();
    aBackendThatIsNotThereIsNotARefusal();
    aRevokedTokenIsARefusalAndSaysWhatToDo();
    anyOtherRefusalIsReportedWithItsStatus();
    aDuplicateIsStillADelivery();
    theTokenIsNeverInWhatComesBack();
    theSerialisationIsTheServersOwn();

    std::cout << "SnapshotPusher tests passed." << std::endl;
    return 0;
}
