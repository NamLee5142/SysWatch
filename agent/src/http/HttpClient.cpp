#include "http/HttpClient.h"

#include <algorithm>
#include <cctype>
#include <cstring>
#include <sstream>
#include <string>
#include <vector>

#if defined(_WIN32)
#include <winsock2.h>
#include <ws2tcpip.h>
using SocketHandle = SOCKET;
#else
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
using SocketHandle = int;
#define INVALID_SOCKET (-1)
#define SOCKET_ERROR (-1)
#endif

namespace http {

namespace {

constexpr std::size_t MaxResponseBytes = 1 * 1024 * 1024;

void closeSocket(SocketHandle handle) {
    if (handle == INVALID_SOCKET) {
        return;
    }
#if defined(_WIN32)
    closesocket(handle);
#else
    ::close(handle);
#endif
}

// Winsock has to be started per process. The server does the same; both are
// reference counted by the OS, so an agent that runs a server and a client
// starts it twice and that is correct.
class Winsock {
public:
    Winsock() {
#if defined(_WIN32)
        WSADATA data;
        ok_ = WSAStartup(MAKEWORD(2, 2), &data) == 0;
#endif
    }

    ~Winsock() {
#if defined(_WIN32)
        if (ok_) {
            WSACleanup();
        }
#endif
    }

    bool ok() const { return ok_; }

private:
    bool ok_{true};
};

bool setBlocking(SocketHandle handle, bool blocking) {
#if defined(_WIN32)
    u_long mode = blocking ? 0 : 1;
    return ioctlsocket(handle, FIONBIO, &mode) == 0;
#else
    const int flags = fcntl(handle, F_GETFL, 0);
    if (flags < 0) {
        return false;
    }
    const int wanted = blocking ? (flags & ~O_NONBLOCK) : (flags | O_NONBLOCK);
    return fcntl(handle, F_SETFL, wanted) == 0;
#endif
}

// Applies to recv and send both. A read timeout alone would leave a send to a
// server that has stopped reading blocked until the OS gave up on it.
void setTimeouts(SocketHandle handle, int timeoutMs) {
#if defined(_WIN32)
    DWORD value = static_cast<DWORD>(timeoutMs);
    setsockopt(handle, SOL_SOCKET, SO_RCVTIMEO, (const char *)&value, sizeof(value));
    setsockopt(handle, SOL_SOCKET, SO_SNDTIMEO, (const char *)&value, sizeof(value));
#else
    timeval value{};
    value.tv_sec = timeoutMs / 1000;
    value.tv_usec = (timeoutMs % 1000) * 1000;
    setsockopt(handle, SOL_SOCKET, SO_RCVTIMEO, &value, sizeof(value));
    setsockopt(handle, SOL_SOCKET, SO_SNDTIMEO, &value, sizeof(value));
#endif
}

bool connectInProgress() {
#if defined(_WIN32)
    return WSAGetLastError() == WSAEWOULDBLOCK;
#else
    return errno == EINPROGRESS;
#endif
}

// Connects with a deadline.
//
// A blocking connect() ignores SO_SNDTIMEO and hands the wait to the OS, which
// on Windows takes about 21 seconds to give up on an address that does not
// answer. An agent with a ten-second timeout that actually waits twenty-one is
// worse than one with no timeout at all, because the number in the
// configuration is a lie. So: non-blocking connect, select for writability,
// then back to blocking for the transfer.
bool connectWithTimeout(SocketHandle handle, const addrinfo *address, int timeoutMs) {
    if (!setBlocking(handle, false)) {
        return false;
    }

    const int result = ::connect(handle, address->ai_addr,
                                 static_cast<int>(address->ai_addrlen));

    if (result != 0) {
        if (!connectInProgress()) {
            return false;
        }

        fd_set writable;
        FD_ZERO(&writable);
        FD_SET(handle, &writable);

        // Winsock reports a *failed* connect in the exception set rather than
        // the write set. Without this, a refused connection is indistinguishable
        // from one still in progress, and the select sits out the whole timeout
        // - five seconds to discover a closed port on loopback, once per push.
        // POSIX signals writability either way, so passing it costs nothing
        // there and the SO_ERROR check below covers both.
        fd_set failed;
        FD_ZERO(&failed);
        FD_SET(handle, &failed);

        timeval deadline{};
        deadline.tv_sec = timeoutMs / 1000;
        deadline.tv_usec = (timeoutMs % 1000) * 1000;

        const int ready = select(static_cast<int>(handle) + 1, nullptr, &writable,
                                 &failed, &deadline);
        if (ready <= 0) {
            return false;  // 0 is the timeout, negative is a failure
        }

        // Writable does not mean connected: a refused connection selects
        // writable too, and the reason is in SO_ERROR.
        int error = 0;
#if defined(_WIN32)
        int length = sizeof(error);
        if (getsockopt(handle, SOL_SOCKET, SO_ERROR, (char *)&error, &length) != 0) {
            return false;
        }
#else
        socklen_t length = sizeof(error);
        if (getsockopt(handle, SOL_SOCKET, SO_ERROR, &error, &length) != 0) {
            return false;
        }
#endif
        if (error != 0) {
            return false;
        }
    }

    return setBlocking(handle, true);
}

bool sendAll(SocketHandle handle, const std::string &data) {
    std::size_t total = 0;
    while (total < data.size()) {
        const int sent = static_cast<int>(
            ::send(handle, data.data() + total,
                   static_cast<int>(data.size() - total), 0));
        if (sent <= 0) {
            return false;
        }
        total += static_cast<std::size_t>(sent);
    }
    return true;
}

std::string trimmed(const std::string &value) {
    const auto begin = value.find_first_not_of(" \t\r\n");
    if (begin == std::string::npos) {
        return "";
    }
    const auto end = value.find_last_not_of(" \t\r\n");
    return value.substr(begin, end - begin + 1);
}

std::string lowercased(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

struct Headers {
    bool chunked{false};
    bool hasLength{false};
    long long length{0};
};

// The status code from "HTTP/1.1 202 Accepted", or 0 if that is not what this
// is. A reply that does not begin with a status line is not an HTTP reply, and
// guessing at one would turn a wrong port into a plausible-looking failure.
int parseStatusLine(const std::string &line) {
    if (line.rfind("HTTP/", 0) != 0) {
        return 0;
    }

    const std::size_t firstSpace = line.find(' ');
    if (firstSpace == std::string::npos) {
        return 0;
    }

    const std::string code = trimmed(line.substr(firstSpace + 1, 4));
    if (code.size() < 3) {
        return 0;
    }

    for (int i = 0; i < 3; ++i) {
        if (std::isdigit(static_cast<unsigned char>(code[i])) == 0) {
            return 0;
        }
    }

    return std::atoi(code.substr(0, 3).c_str());
}

Headers parseHeaders(const std::string &block) {
    Headers headers;
    std::istringstream lines(block);
    std::string line;

    // The first line is the status line, already read by the caller.
    std::getline(lines, line);

    while (std::getline(lines, line)) {
        const std::size_t colon = line.find(':');
        if (colon == std::string::npos) {
            continue;
        }

        const std::string name = lowercased(trimmed(line.substr(0, colon)));
        const std::string value = trimmed(line.substr(colon + 1));

        if (name == "content-length") {
            headers.hasLength = true;
            headers.length = std::atoll(value.c_str());
        } else if (name == "transfer-encoding" && lowercased(value).find("chunked") !=
                                                      std::string::npos) {
            headers.chunked = true;
        }
    }

    return headers;
}

} // namespace

HttpResult HttpClient::get(const Url &url) const {
    return send(url, "GET", "", "", "");
}

HttpResult HttpClient::post(const Url &url,
                            const std::string &body,
                            const std::string &contentType,
                            const std::string &bearerToken) const {
    return send(url, "POST", body, contentType, bearerToken);
}

HttpResult HttpClient::send(const Url &url,
                            const std::string &method,
                            const std::string &body,
                            const std::string &contentType,
                            const std::string &bearerToken) const {
    HttpResult result;

    if (url.scheme == "https") {
        // Said plainly rather than attempted. A TLS handshake spoken to as if
        // it were HTTP produces a parse failure somewhere deep in the response
        // reader, and the operator reads that instead of "no".
        result.error = "https is not supported; the agent speaks plain HTTP only";
        return result;
    }

    Winsock winsock;
    if (!winsock.ok()) {
        result.error = "the network stack could not be initialised";
        return result;
    }

    addrinfo hints{};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_protocol = IPPROTO_TCP;

    const std::string port = std::to_string(url.port);
    addrinfo *addresses = nullptr;
    if (getaddrinfo(url.host.c_str(), port.c_str(), &hints, &addresses) != 0 ||
        addresses == nullptr) {
        result.error = "the host name could not be resolved";
        return result;
    }

    SocketHandle handle = ::socket(addresses->ai_family, addresses->ai_socktype,
                                   addresses->ai_protocol);
    if (handle == INVALID_SOCKET) {
        freeaddrinfo(addresses);
        result.error = "a socket could not be opened";
        return result;
    }

    if (!connectWithTimeout(handle, addresses, timeoutMs_)) {
        freeaddrinfo(addresses);
        closeSocket(handle);
        result.error = "the backend could not be reached";
        return result;
    }
    freeaddrinfo(addresses);

    setTimeouts(handle, timeoutMs_);

    std::ostringstream request;
    request << method << ' ' << url.path << " HTTP/1.1\r\n"
            << "Host: " << url.host << ':' << url.port << "\r\n"
            // No keep-alive. One request per connection costs a handshake every
            // poll interval and removes every question about a reused socket
            // whose far end went away while it was idle.
            << "Connection: close\r\n";

    if (!bearerToken.empty()) {
        request << "Authorization: Bearer " << bearerToken << "\r\n";
    }
    if (!contentType.empty()) {
        request << "Content-Type: " << contentType << "\r\n";
    }
    // Always sent, including as 0: a POST with no Content-Length and no
    // chunked encoding is one a server is entitled to read as having no body.
    if (method != "GET") {
        request << "Content-Length: " << body.size() << "\r\n";
    }
    request << "\r\n" << body;

    if (!sendAll(handle, request.str())) {
        closeSocket(handle);
        result.error = "the request could not be sent";
        return result;
    }

    std::string received;
    std::vector<char> buffer(4096);
    while (received.size() < MaxResponseBytes) {
        const int read = static_cast<int>(
            ::recv(handle, buffer.data(), static_cast<int>(buffer.size()), 0));
        if (read == 0) {
            break;  // the server closed, which Connection: close asked it to
        }
        if (read < 0) {
            closeSocket(handle);
            result.error = "the backend stopped responding";
            return result;
        }
        received.append(buffer.data(), static_cast<std::size_t>(read));

        // Stop as soon as the body is complete rather than waiting for the
        // close. A server that ignores Connection: close would otherwise hold
        // this until the read timeout, once per push.
        const std::size_t end = received.find("\r\n\r\n");
        if (end != std::string::npos) {
            const Headers headers = parseHeaders(received.substr(0, end));
            if (headers.hasLength &&
                received.size() >= end + 4 + static_cast<std::size_t>(headers.length)) {
                break;
            }
        }
    }
    closeSocket(handle);

    const std::size_t headerEnd = received.find("\r\n\r\n");
    if (headerEnd == std::string::npos) {
        result.error = "the reply was not an HTTP response";
        return result;
    }

    const std::string head = received.substr(0, headerEnd);
    const std::string firstLine = head.substr(0, head.find("\r\n"));

    const int status = parseStatusLine(firstLine);
    if (status == 0) {
        result.error = "the reply was not an HTTP response";
        return result;
    }

    const Headers headers = parseHeaders(head);
    std::string payload = received.substr(headerEnd + 4);

    if (headers.chunked) {
        // Refused rather than decoded. Nothing this agent talks to sends a
        // chunked reply to a small POST, and a half-implemented dechunker that
        // silently returns framing bytes as if they were the body is a worse
        // outcome than a clear refusal.
        result.error = "the backend sent a chunked response, which is not supported";
        return result;
    }

    if (headers.hasLength) {
        const auto expected = static_cast<std::size_t>(headers.length);
        if (payload.size() < expected) {
            // The connection ended early. Returning what arrived would hand the
            // caller a truncated body indistinguishable from a complete one.
            result.error = "the response body was shorter than it claimed";
            return result;
        }
        payload.resize(expected);
    }

    result.reached = true;
    result.status = status;
    result.body = payload;
    return result;
}

} // namespace http
