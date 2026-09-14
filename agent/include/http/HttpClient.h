#pragma once

#include "http/Url.h"

#include <chrono>
#include <string>

namespace http {

// What came back, or why nothing did.
//
// `reached` separates the two questions an agent has to answer differently: a
// backend that refused the connection is a reason to keep the snapshot and try
// again, while a backend that answered 401 is a reason to stop and tell
// somebody. Both are "the push did not work", and treating them alike would
// either retry a bad credential forever or discard readings over a blip.
struct HttpResult {
    bool reached{false};
    int status{0};
    std::string body;
    // Set only when reached is false. Names what failed - a hostname, a
    // timeout, a refused connection - and never carries the request, because
    // the request carries the credential.
    std::string error;

    bool isSuccess() const { return reached && status >= 200 && status < 300; }
};

// A blocking HTTP/1.1 client, enough for one request at a time to one backend.
//
// Deliberately small. The agent makes one kind of call - POST some JSON, read
// a short answer - and a general client would be more surface than the whole
// rest of the networking code. What it does not do is as much of the design as
// what it does: no redirects (a redirect for an authenticated POST is a
// configuration mistake, and following one would send the credential
// somewhere it was not written for), no keep-alive, no chunked responses, no
// TLS. https:// parses so that the loopback rule can refuse it clearly rather
// than failing to connect for reasons nobody can read.
class HttpClient {
public:
    static constexpr int DefaultTimeoutMs = 10000;

    explicit HttpClient(int timeoutMs = DefaultTimeoutMs) : timeoutMs_(timeoutMs) {}

    HttpResult get(const Url &url) const;

    // bearerToken is sent as `Authorization: Bearer <token>` when non-empty.
    // Passed per call rather than held on the client so that nothing owns a
    // credential for longer than the request that needs it.
    HttpResult post(const Url &url,
                    const std::string &body,
                    const std::string &contentType = "application/json",
                    const std::string &bearerToken = "") const;

private:
    int timeoutMs_;

    HttpResult send(const Url &url,
                    const std::string &method,
                    const std::string &body,
                    const std::string &contentType,
                    const std::string &bearerToken) const;
};

} // namespace http
