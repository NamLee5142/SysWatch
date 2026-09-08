#pragma once

#include "domain/Snapshot.h"
#include "http/HttpClient.h"
#include "http/Url.h"

#include <functional>
#include <string>

namespace push {

// Sends each collected snapshot to a backend that may be on another machine.
//
// The direction matters and is the whole reason this exists: the agent opens
// the connection outward, so a monitored machine needs no inbound port, no
// firewall rule and no routable address. See
// docs/decisions/0001-agents-push-to-the-backend.md.
//
// Nothing here logs the token. The destination is logged - an operator
// debugging a push needs to know where it went - and the token is not part of
// it, which is why Url::parse refuses a URL with credentials in it.
class SnapshotPusher {
public:
    // What to say about an attempt, for a caller that logs. Deliberately not an
    // exception: a push that fails is an ordinary event on a machine whose
    // network comes and goes, and collection carries on regardless.
    struct Outcome {
        bool delivered{false};
        // True when the backend answered and refused - a revoked token, a
        // payload it would not take. Retrying changes nothing, so the agent
        // should say so rather than repeat itself.
        bool refused{false};
        std::string detail;
    };

    SnapshotPusher(http::Url destination, std::string token, int timeoutMs)
        : destination_(std::move(destination)),
          token_(std::move(token)),
          client_(timeoutMs) {}

    Outcome push(const Snapshot &snapshot) const;

    const http::Url &destination() const { return destination_; }

private:
    http::Url destination_;
    std::string token_;
    http::HttpClient client_;
};

} // namespace push
