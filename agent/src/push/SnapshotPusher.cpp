#include "push/SnapshotPusher.h"

#include "http/SnapshotJson.h"

#include <string>

namespace push {

SnapshotPusher::Outcome SnapshotPusher::push(const Snapshot &snapshot) const {
    Outcome outcome;

    const http::HttpResult result =
        client_.post(destination_, http::snapshotToJson(snapshot), "application/json",
                     token_);

    if (!result.reached) {
        // The backend was not there. Worth retrying, and worth saying without
        // alarm: a laptop that closed its lid produces this every time it wakes.
        outcome.detail = result.error;
        return outcome;
    }

    if (result.isSuccess()) {
        outcome.delivered = true;
        return outcome;
    }

    // The backend answered and said no. 401 is the one an operator has to act
    // on - a token that was revoked, or was never issued for this machine - and
    // it is worth naming, because it is indistinguishable from a working agent
    // from the outside: the service is up, the collector is collecting, and
    // nothing arrives.
    outcome.refused = true;
    if (result.status == 401) {
        outcome.detail =
            "the backend rejected the agent's credential (401). Issue a token "
            "for this host and put it in the agent's configuration";
    } else {
        outcome.detail = "the backend answered " + std::to_string(result.status);
    }

    return outcome;
}

} // namespace push
