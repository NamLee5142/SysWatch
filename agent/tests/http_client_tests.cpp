// The agent's HTTP client, against the agent's own HTTP server.
//
// Two hand-rolled implementations of the same protocol, talking to each other.
// That is a weaker check than talking to somebody else's server - both were
// written here, so a shared misreading of RFC 9112 would pass - but it is the
// one a test can make on any machine, and commit 8 puts the client in front of
// the real backend by hand.
//
// The failures matter more than the success. A client that reports "reached,
// status 200" for a truncated body, or waits twenty seconds on a ten-second
// timeout, is worse than one that does not connect at all: the agent above it
// makes decisions from those answers.

#include "agent/Agent.h"
#include "http/HTTPServer.h"
#include "http/HttpClient.h"
#include "http/Url.h"

#include <cassert>
#include <chrono>
#include <iostream>
#include <string>
#include <thread>

namespace {

constexpr unsigned short ServerPort = 54331;
// Nothing listens here. Distinct from every other port in the suite.
constexpr unsigned short DeadPort = 54332;

http::Url at(const std::string &text) {
    http::Url url;
    const bool ok = http::Url::parse(text, url);
    assert(ok);
    return url;
}

std::string base() {
    return "http://127.0.0.1:" + std::to_string(ServerPort);
}

void getsARealResponse() {
    const http::HttpClient client;

    const auto result = client.get(at(base() + "/snapshot"));

    assert(result.reached);
    assert(result.status == 200);
    assert(result.isSuccess());
    assert(result.error.empty());
    // The body is the snapshot the server just rendered, and it is complete:
    // Content-Length was honoured rather than the reader stopping at the first
    // packet boundary.
    assert(result.body.find("cpuInfo") != std::string::npos);
    assert(result.body.find("systemInfo") != std::string::npos);
    assert(result.body.back() == '}');
}

void readsANonSuccessStatusWithoutCallingItAFailure() {
    // 404 is an answer, not a failure to reach. An agent must be able to tell
    // "the backend said no" from "there was no backend", because one is worth
    // retrying and the other is worth reporting.
    const http::HttpClient client;

    const auto result = client.get(at(base() + "/no-such-path"));

    assert(result.reached);
    assert(result.status == 404);
    assert(!result.isSuccess());
    assert(result.error.empty());
}

void sendsAPostWithABodyAndAToken() {
    // The server answers 404 to a POST - it routes GET /snapshot and nothing
    // else - which is exactly what this needs: the request was framed well
    // enough to be understood and rejected on its merits.
    const http::HttpClient client;

    const auto result = client.post(at(base() + "/ingest/snapshot"),
                                    "{\"collectedAt\":\"2026-09-08T10:00:00Z\"}",
                                    "application/json",
                                    "a-token-that-must-not-appear-anywhere");

    assert(result.reached);
    assert(result.status == 404);
    // Whatever went wrong, the credential is not in what comes back.
    assert(result.body.find("a-token-that-must-not-appear-anywhere") == std::string::npos);
    assert(result.error.find("a-token-that-must-not-appear-anywhere") == std::string::npos);
}

void refusedConnectionIsNotReached() {
    const http::HttpClient client;

    const auto result = client.get(at("http://127.0.0.1:" + std::to_string(DeadPort) + "/x"));

    assert(!result.reached);
    assert(result.status == 0);
    assert(!result.error.empty());
    assert(!result.isSuccess());
}

void aRefusalIsFastRatherThanTheTimeout() {
    // A refused connection returns immediately; it must not sit out the whole
    // timeout. The agent pushes on the collection interval, and a client that
    // spends ten seconds discovering a closed port would stall collection.
    const http::HttpClient client(5000);

    const auto start = std::chrono::steady_clock::now();
    client.get(at("http://127.0.0.1:" + std::to_string(DeadPort) + "/x"));
    const auto elapsed = std::chrono::steady_clock::now() - start;

    assert(elapsed < std::chrono::seconds(4));
}

void anUnresolvableHostIsNotReached() {
    const http::HttpClient client;

    const auto result = client.get(at("http://no-such-host.invalid/x"));

    assert(!result.reached);
    assert(!result.error.empty());
}

void httpsIsRefusedClearly() {
    // Rather than attempted and failed somewhere in the response reader, which
    // is what speaking HTTP at a TLS port looks like from the inside.
    const http::HttpClient client;

    const auto result = client.get(at("https://example.com/x"));

    assert(!result.reached);
    assert(result.error.find("https") != std::string::npos);
}

void timeoutIsHonoured() {
    // Connecting to an address that neither answers nor refuses. 203.0.113.0/24
    // is TEST-NET-3, reserved by RFC 5737 for documentation and routed
    // nowhere, so packets to it are dropped rather than rejected - which is the
    // case a blocking connect() would sit on for about twenty seconds.
    const http::HttpClient client(1500);

    const auto start = std::chrono::steady_clock::now();
    const auto result = client.get(at("http://203.0.113.1:8000/x"));
    const auto elapsed = std::chrono::steady_clock::now() - start;

    assert(!result.reached);
    // Generous upper bound: the point is that the OS default did not apply.
    assert(elapsed < std::chrono::seconds(8));
}

} // namespace

int main() {
    agent::Agent agent;
    http::HTTPServer server(agent, ServerPort);

    server.start();
    agent.start();
    std::this_thread::sleep_for(std::chrono::seconds(2));
    assert(server.isRunning());

    getsARealResponse();
    readsANonSuccessStatusWithoutCallingItAFailure();
    sendsAPostWithABodyAndAToken();
    refusedConnectionIsNotReached();
    aRefusalIsFastRatherThanTheTimeout();
    anUnresolvableHostIsNotReached();
    httpsIsRefusedClearly();
    timeoutIsHonoured();

    agent.stop();
    server.stop();

    std::cout << "HttpClient tests passed." << std::endl;
    return 0;
}
