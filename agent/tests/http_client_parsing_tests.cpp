// The client against a server that answers badly on purpose.
//
// The round-trip tests use the agent's own HTTP server, which is well behaved:
// it always sends a status line, always sends Content-Length, and never sends
// a chunked body. Everything that goes wrong in the field is therefore untested
// by them.
//
// This is a socket that writes exactly the bytes each case needs. It is not an
// HTTP server and does not try to be - it accepts one connection, reads until
// the request ends, writes a fixed reply, and closes.

#include "http/HttpClient.h"
#include "http/Url.h"

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

constexpr unsigned short Port = 54333;

void closeHandle(SocketHandle handle) {
#if defined(_WIN32)
    closesocket(handle);
#else
    ::close(handle);
#endif
}

// Serves `reply` verbatim to one caller, then stops.
class RudeServer {
public:
    explicit RudeServer(std::string reply, bool closeEarly = false)
        : reply_(std::move(reply)), closeEarly_(closeEarly) {
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

    ~RudeServer() {
        if (thread_.joinable()) {
            thread_.join();
        }
        closeHandle(listen_);
#if defined(_WIN32)
        WSACleanup();
#endif
    }

private:
    void serve() {
        SocketHandle client = ::accept(listen_, nullptr, nullptr);
        if (client == INVALID_SOCKET) {
            return;
        }

        // Read the request so the client's send() completes.
        char buffer[4096];
        ::recv(client, buffer, sizeof(buffer), 0);

        if (!reply_.empty()) {
            ::send(client, reply_.data(), (int)reply_.size(), 0);
        }
        if (closeEarly_) {
            // Close mid-body, which is what a backend being restarted does.
        }
        closeHandle(client);
    }

    std::string reply_;
    bool closeEarly_;
    SocketHandle listen_{INVALID_SOCKET};
    std::thread thread_;
};

http::Url target() {
    http::Url url;
    const bool ok = http::Url::parse("http://127.0.0.1:" + std::to_string(Port) + "/x", url);
    assert(ok);
    return url;
}

http::HttpResult ask(const std::string &reply) {
    RudeServer server(reply);
    // Short timeout: several of these end with the server having said nothing
    // more, and the client should not wait out a long one to find that out.
    return http::HttpClient(2000).get(target());
}

void readsAWellFormedReply() {
    const auto result = ask("HTTP/1.1 202 Accepted\r\nContent-Length: 2\r\n\r\nok");

    assert(result.reached);
    assert(result.status == 202);
    assert(result.body == "ok");
}

void bodyIsCutToContentLength() {
    // A server that sends more than it declared. Returning the extra would let
    // whatever follows the body - a second reply, framing, anything - be read
    // as part of it.
    const auto result = ask("HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nokEXTRA");

    assert(result.reached);
    assert(result.body == "ok");
}

void aShortBodyIsAFailureNotATruncatedSuccess() {
    // The case the roadmap called out. A body shorter than Content-Length means
    // the connection ended early; handing back what arrived would be
    // indistinguishable from a complete answer.
    const auto result = ask("HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nshort");

    assert(!result.reached);
    assert(result.error.find("shorter") != std::string::npos);
}

void chunkedIsRefusedRatherThanMisread() {
    const auto result =
        ask("HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\nok\r\n0\r\n\r\n");

    assert(!result.reached);
    assert(result.error.find("chunked") != std::string::npos);
    // Crucially, not "ok" plus framing bytes reported as a success.
    assert(result.body.empty());
}

void headersAreCaseInsensitive() {
    // RFC 9110: field names are case-insensitive, and real servers vary.
    const auto result = ask("HTTP/1.1 200 OK\r\ncOnTeNt-LeNgTh: 2\r\n\r\nok");

    assert(result.reached);
    assert(result.body == "ok");
}

void noContentLengthReadsToClose() {
    // Legal under Connection: close, and what a minimal server does.
    const auto result = ask("HTTP/1.1 200 OK\r\n\r\nthe whole body");

    assert(result.reached);
    assert(result.body == "the whole body");
}

void anEmptyBodyIsFine() {
    const auto result = ask("HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n");

    assert(result.reached);
    assert(result.status == 204);
    assert(result.body.empty());
}

void somethingThatIsNotHttpIsRefused() {
    // A wrong port - an SMTP server, an SSH banner, a TLS hello. Reporting a
    // parse of these as a status would be worse than saying no.
    for (const std::string reply : {std::string("220 mail.example.com ESMTP\r\n"),
                                    std::string("SSH-2.0-OpenSSH_9.0\r\n\r\n"),
                                    std::string("\x16\x03\x01\x00\x50 binary\r\n\r\n"),
                                    std::string("just some text\r\n\r\n")}) {
        const auto result = ask(reply);
        assert(!result.reached);
        assert(result.status == 0);
    }
}

void aSilentServerTimesOutRatherThanHanging() {
    const auto start = std::chrono::steady_clock::now();
    const auto result = ask("");
    const auto elapsed = std::chrono::steady_clock::now() - start;

    assert(!result.reached);
    assert(elapsed < std::chrono::seconds(6));
}

void headersWithNoStatusLineAreRefused() {
    const auto result = ask("Content-Length: 2\r\n\r\nok");

    assert(!result.reached);
}

void aMalformedStatusLineIsRefused() {
    for (const std::string reply : {std::string("HTTP/1.1\r\n\r\n"),
                                    std::string("HTTP/1.1 \r\n\r\n"),
                                    std::string("HTTP/1.1 abc OK\r\n\r\n"),
                                    std::string("HTTP/1.1 2 OK\r\n\r\n")}) {
        const auto result = ask(reply);
        assert(!result.reached);
    }
}

void everyStatusClassIsReported() {
    for (const auto pair : {std::pair<std::string, int>{"200 OK", 200},
                            {"201 Created", 201},
                            {"202 Accepted", 202},
                            {"401 Unauthorized", 401},
                            {"404 Not Found", 404},
                            {"500 Internal Server Error", 500}}) {
        const auto result = ask("HTTP/1.1 " + pair.first + "\r\nContent-Length: 0\r\n\r\n");
        assert(result.reached);
        assert(result.status == pair.second);
    }

    // And only 2xx counts as success, which is what the agent branches on.
    assert(ask("HTTP/1.1 202 Accepted\r\nContent-Length: 0\r\n\r\n").isSuccess());
    assert(!ask("HTTP/1.1 302 Found\r\nContent-Length: 0\r\n\r\n").isSuccess());
    assert(!ask("HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n").isSuccess());
}

void aRedirectIsNotFollowed() {
    // Following one would send the credential to an address nobody configured.
    const auto result =
        ask("HTTP/1.1 302 Found\r\nLocation: http://elsewhere.example.com/\r\n"
            "Content-Length: 0\r\n\r\n");

    assert(result.reached);
    assert(result.status == 302);
    assert(!result.isSuccess());
}

} // namespace

int main() {
    readsAWellFormedReply();
    bodyIsCutToContentLength();
    aShortBodyIsAFailureNotATruncatedSuccess();
    chunkedIsRefusedRatherThanMisread();
    headersAreCaseInsensitive();
    noContentLengthReadsToClose();
    anEmptyBodyIsFine();
    somethingThatIsNotHttpIsRefused();
    aSilentServerTimesOutRatherThanHanging();
    headersWithNoStatusLineAreRefused();
    aMalformedStatusLineIsRefused();
    everyStatusClassIsReported();
    aRedirectIsNotFollowed();

    std::cout << "HttpClient parsing tests passed." << std::endl;
    return 0;
}
