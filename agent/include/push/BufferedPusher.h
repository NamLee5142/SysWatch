#pragma once

#include "domain/Snapshot.h"
#include "push/SnapshotPusher.h"

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>

namespace push {

// Holds snapshots until the backend will take them, and sends them from a
// thread of its own.
//
// Two problems, one object.
//
// The first is that a push is network I/O and collection is not. Commit 8 put
// the push on the collection thread, where an unreachable backend delayed the
// next collection by the whole timeout - ten seconds of blindness, every ten
// seconds, on a machine whose network had gone. Handing the snapshot to another
// thread makes collection take as long as collecting.
//
// The second is that a backend is not always there. A laptop suspends, a
// backend restarts, a switch reboots. Without a buffer every reading taken
// during that window is gone, which is precisely the window somebody will want
// to look at afterwards.
//
// The buffer is bounded and drops the oldest. Metrics age badly: given the
// choice between the reading from an hour ago and the one from this second,
// the recent one is worth more, and an unbounded queue on a machine whose
// backend has been down for a week is a memory leak with a justification.
class BufferedPusher {
public:
    // 512 snapshots. Sized by memory rather than by time, because the
    // collection interval is configurable and a number of minutes would mean
    // something different on every install. A snapshot serialises to roughly a
    // kilobyte or two with a full process list, so this is a megabyte or so
    // held at worst - small beside the agent's own footprint, and large enough
    // to cover eight minutes at the one-second floor or an hour and a half at
    // the ten-second interval a deployment actually uses.
    static constexpr std::size_t DefaultCapacity = 512;

    // How long to wait before trying again after a failure. Without it the
    // thread would retry at the speed of the connect() call, which against a
    // closed port on loopback is fast enough to be a spin loop.
    static constexpr int RetryDelayMs = 2000;

    using Log = std::function<void(const std::string &)>;

    // retryDelayMs is a parameter rather than only a constant so a test can
    // watch several retries without waiting several seconds for each. Nothing
    // that ships passes anything but the default.
    BufferedPusher(SnapshotPusher pusher,
                   Log onInfo,
                   Log onWarning,
                   std::size_t capacity = DefaultCapacity,
                   int retryDelayMs = RetryDelayMs);
    ~BufferedPusher();

    void start();
    void stop();

    // Takes a copy and returns. Never blocks on the network, and never blocks
    // on a full buffer - it makes room instead.
    void offer(const Snapshot &snapshot);

    struct Stats {
        std::size_t queued{0};
        std::size_t delivered{0};
        std::size_t dropped{0};
        std::size_t refused{0};
    };

    Stats stats() const;

private:
    void drain();

    SnapshotPusher pusher_;
    Log onInfo_;
    Log onWarning_;
    std::size_t capacity_;
    int retryDelayMs_;

    mutable std::mutex mutex_;
    std::condition_variable wakeup_;
    std::deque<Snapshot> queue_;
    std::size_t delivered_{0};
    std::size_t dropped_{0};
    std::size_t refused_{0};

    std::atomic<bool> running_{false};
    std::thread thread_;
};

} // namespace push
