// Holding snapshots while the backend is not there.
//
// The backend is a socket that can be started and stopped between assertions,
// which is the whole point: what this file is about is what the agent does
// across an outage, and an outage is something a test has to be able to cause.

#include "domain/Snapshot.h"
#include "http/Url.h"
#include "push/BufferedPusher.h"
#include "push/SnapshotPusher.h"

#include <atomic>
#include <cassert>
#include <chrono>
#include <iostream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

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

constexpr unsigned short Port = 54370;

void closeHandle(SocketHandle handle) {
#if defined(_WIN32)
    closesocket(handle);
#else
    ::close(handle);
#endif
}

// A backend that can be switched off and on again, and counts what it took.
class Backend {
public:
    explicit Backend(std::string reply = "HTTP/1.1 202 Accepted\r\nContent-Length: 0\r\n\r\n")
        : reply_(std::move(reply)) {
#if defined(_WIN32)
        WSADATA data;
        WSAStartup(MAKEWORD(2, 2), &data);
#endif
    }

    ~Backend() {
        stop();
#if defined(_WIN32)
        WSACleanup();
#endif
    }

    void start() {
        if (running_.exchange(true)) {
            return;
        }
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
        assert(::listen(listen_, 16) == 0);
        thread_ = std::thread([this] { serve(); });
    }

    void stop() {
        if (!running_.exchange(false)) {
            return;
        }
        closeHandle(listen_);
        listen_ = INVALID_SOCKET;
        if (thread_.joinable()) {
            thread_.join();
        }
    }

    int taken() const { return taken_.load(); }

private:
    void serve() {
        while (running_.load()) {
            SocketHandle client = ::accept(listen_, nullptr, nullptr);
            if (client == INVALID_SOCKET) {
                return;  // the listener was closed
            }
            char buffer[8192];
            ::recv(client, buffer, sizeof(buffer), 0);
            ::send(client, reply_.data(), (int)reply_.size(), 0);
            closeHandle(client);
            ++taken_;
        }
    }

    std::string reply_;
    std::atomic<bool> running_{false};
    std::atomic<int> taken_{0};
    SocketHandle listen_{INVALID_SOCKET};
    std::thread thread_;
};

http::Url destination() {
    http::Url url;
    const bool ok = http::Url::parse(
        "http://127.0.0.1:" + std::to_string(Port) + "/api/ingest/snapshot", url);
    assert(ok);
    return url;
}

Snapshot aSnapshot(double cpu = 10.0) {
    Snapshot snapshot;
    snapshot.collectedAt = std::chrono::system_clock::now();
    snapshot.cpuInfo.coreCount = 8;
    snapshot.cpuInfo.usagePercent = cpu;
    snapshot.systemInfo.hostName = "buildbox";
    return snapshot;
}

// A short retry delay throughout. The delay's real value is about not spinning
// against a closed port; watching six retries at the shipped two seconds would
// spend twelve seconds proving something a tenth of that proves as well.
constexpr int TestRetryMs = 100;

std::unique_ptr<push::BufferedPusher> pusherWith(std::size_t capacity,
                                                 std::vector<std::string> *lines = nullptr) {
    auto record = [lines](const std::string &message) {
        if (lines) {
            lines->push_back(message);
        }
    };
    return std::make_unique<push::BufferedPusher>(
        push::SnapshotPusher(destination(), "a-token", 1000), record, record, capacity,
        TestRetryMs);
}

// Waits for a condition rather than sleeping a fixed time: the drain runs on
// its own thread and a fixed wait is either slow or flaky.
template <typename Predicate>
bool eventually(Predicate ready, int timeoutMs = 8000) {
    const auto deadline =
        std::chrono::steady_clock::now() + std::chrono::milliseconds(timeoutMs);
    while (std::chrono::steady_clock::now() < deadline) {
        if (ready()) {
            return true;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(25));
    }
    return ready();
}

void deliversWhatItIsGiven() {
    Backend backend;
    backend.start();

    auto pusher = pusherWith(16);
    pusher->start();
    for (int i = 0; i < 3; ++i) {
        pusher->offer(aSnapshot());
    }

    assert(eventually([&] { return pusher->stats().delivered == 3; }));
    assert(pusher->stats().queued == 0);
    assert(pusher->stats().dropped == 0);
    pusher->stop();
}

void offeringDoesNotBlockOnTheNetwork() {
    // The reason this class exists. With the push on the collection thread, an
    // unreachable backend delayed the next collection by the whole timeout.
    // Nothing is listening here, and offer() still has to return at once.
    auto pusher = pusherWith(16);
    pusher->start();

    const auto start = std::chrono::steady_clock::now();
    for (int i = 0; i < 20; ++i) {
        pusher->offer(aSnapshot());
    }
    const auto elapsed = std::chrono::steady_clock::now() - start;

    assert(elapsed < std::chrono::milliseconds(500));
    pusher->stop();
}

void holdsSnapshotsWhileTheBackendIsAway() {
    auto pusher = pusherWith(64);
    pusher->start();

    for (int i = 0; i < 5; ++i) {
        pusher->offer(aSnapshot(static_cast<double>(i)));
    }

    // Nothing is listening, so nothing is delivered and nothing is lost.
    assert(eventually([&] { return pusher->stats().queued == 5; }, 3000));
    assert(pusher->stats().delivered == 0);
    assert(pusher->stats().dropped == 0);
    pusher->stop();
}

void sendsTheHeldSnapshotsWhenTheBackendReturns() {
    // The done-when: an outage costs nothing while the buffer holds.
    Backend backend;
    auto pusher = pusherWith(64);
    pusher->start();

    for (int i = 0; i < 5; ++i) {
        pusher->offer(aSnapshot(static_cast<double>(i)));
    }
    assert(eventually([&] { return pusher->stats().queued == 5; }, 3000));

    backend.start();

    assert(eventually([&] { return pusher->stats().delivered == 5; }));
    assert(pusher->stats().queued == 0);
    assert(pusher->stats().dropped == 0);
    pusher->stop();
}

void dropsTheOldestWhenFull() {
    // Bounded, and the bound is what stops a week-long outage becoming a memory
    // leak. The oldest goes because the recent reading is the one worth having.
    auto pusher = pusherWith(4);
    pusher->start();

    for (int i = 0; i < 10; ++i) {
        pusher->offer(aSnapshot(static_cast<double>(i)));
    }

    const auto stats = pusher->stats();
    assert(stats.queued <= 4);
    assert(stats.dropped >= 6);
    pusher->stop();
}

void memoryDoesNotGrowWhileTheBackendIsDown() {
    // The other half of the done-when, expressed as the thing that can be
    // measured: the queue never exceeds its capacity however long the outage.
    auto pusher = pusherWith(8);
    pusher->start();

    for (int i = 0; i < 500; ++i) {
        pusher->offer(aSnapshot());
        assert(pusher->stats().queued <= 8);
    }

    assert(pusher->stats().queued <= 8);
    pusher->stop();
}

void whatSurvivesIsTheNewest() {
    Backend backend;
    auto pusher = pusherWith(2);
    pusher->start();

    for (int i = 0; i < 6; ++i) {
        pusher->offer(aSnapshot(static_cast<double>(i)));
    }
    assert(eventually([&] { return pusher->stats().queued == 2; }, 3000));

    backend.start();
    assert(eventually([&] { return pusher->stats().delivered == 2; }));
    pusher->stop();
}

void aRefusedSnapshotIsDiscardedRatherThanRetriedForever() {
    // The backend answered and said no. Retrying sends the same document for
    // the same answer, and the buffer behind it would fill with readings that
    // can never drain - so a bad token would cost the recent history too.
    Backend backend("HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n");
    backend.start();

    std::vector<std::string> lines;
    auto pusher = pusherWith(16, &lines);
    pusher->start();
    pusher->offer(aSnapshot());
    pusher->offer(aSnapshot(2.0));

    assert(eventually([&] { return pusher->stats().refused == 2; }));
    assert(pusher->stats().queued == 0);
    assert(pusher->stats().delivered == 0);

    bool explained = false;
    for (const auto &line : lines) {
        if (line.find("refused") != std::string::npos) {
            explained = true;
        }
    }
    assert(explained);
    pusher->stop();
}

void stoppingIsPromptEvenMidRetry() {
    // The retry delay must not become the shutdown delay: a Windows Service
    // that takes seconds to stop is one the SCM eventually kills.
    auto pusher = pusherWith(8);
    pusher->start();
    pusher->offer(aSnapshot());

    // Let it fail once and settle into the retry wait.
    std::this_thread::sleep_for(std::chrono::milliseconds(300));

    const auto start = std::chrono::steady_clock::now();
    pusher->stop();
    const auto elapsed = std::chrono::steady_clock::now() - start;

    assert(elapsed < std::chrono::milliseconds(1000));
}

void stoppingWithoutStartingIsSafe() {
    auto pusher = pusherWith(8);
    pusher->stop();

    auto other = pusherWith(8);
    other->start();
    other->start();  // twice
    other->stop();
    other->stop();
}

void theLogQuietensDownButSaysSoFirst() {
    std::vector<std::string> lines;
    auto pusher = pusherWith(8, &lines);
    pusher->start();
    pusher->offer(aSnapshot());

    // Long enough for several retries at the retry delay.
    assert(eventually(
        [&] {
            for (const auto &line : lines) {
                if (line.find("Still cannot reach the backend") != std::string::npos) {
                    return true;
                }
            }
            return false;
        },
        8000));

    pusher->stop();

    // And it did not write a line per attempt on the way there.
    assert(lines.size() < 12);
}

} // namespace

int main() {
    deliversWhatItIsGiven();
    offeringDoesNotBlockOnTheNetwork();
    holdsSnapshotsWhileTheBackendIsAway();
    sendsTheHeldSnapshotsWhenTheBackendReturns();
    dropsTheOldestWhenFull();
    memoryDoesNotGrowWhileTheBackendIsDown();
    whatSurvivesIsTheNewest();
    aRefusedSnapshotIsDiscardedRatherThanRetriedForever();
    stoppingIsPromptEvenMidRetry();
    stoppingWithoutStartingIsSafe();
    theLogQuietensDownButSaysSoFirst();

    std::cout << "BufferedPusher tests passed." << std::endl;
    return 0;
}
