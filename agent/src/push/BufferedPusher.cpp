#include "push/BufferedPusher.h"

#include <chrono>
#include <string>
#include <utility>

namespace push {

namespace {

// How many consecutive failures before the log stops repeating itself. A
// backend down for a day should not have written a line per collection saying
// so; the backend's own poller thins out the same way.
constexpr int FailuresBeforeQuieting = 5;

} // namespace

BufferedPusher::BufferedPusher(SnapshotPusher pusher,
                               Log onInfo,
                               Log onWarning,
                               std::size_t capacity,
                               int retryDelayMs)
    : pusher_(std::move(pusher)),
      onInfo_(std::move(onInfo)),
      onWarning_(std::move(onWarning)),
      capacity_(capacity == 0 ? 1 : capacity),
      retryDelayMs_(retryDelayMs) {}

BufferedPusher::~BufferedPusher() {
    stop();
}

void BufferedPusher::start() {
    if (running_.exchange(true)) {
        return;
    }
    thread_ = std::thread([this] { drain(); });
}

void BufferedPusher::stop() {
    if (!running_.exchange(false)) {
        return;
    }

    wakeup_.notify_all();
    if (thread_.joinable()) {
        // Joins rather than detaches. A push already in flight finishes or
        // times out, which is bounded by the client's timeout - and a detached
        // thread writing to a Logger the runtime is about to destroy is a
        // crash on the way out of a service stop.
        thread_.join();
    }
}

void BufferedPusher::offer(const Snapshot &snapshot) {
    {
        std::lock_guard<std::mutex> guard(mutex_);

        if (queue_.size() >= capacity_) {
            queue_.pop_front();
            ++dropped_;
        }
        queue_.push_back(snapshot);
    }
    wakeup_.notify_one();
}

BufferedPusher::Stats BufferedPusher::stats() const {
    std::lock_guard<std::mutex> guard(mutex_);
    return Stats{queue_.size(), delivered_, dropped_, refused_};
}

void BufferedPusher::drain() {
    int failures = 0;

    while (running_.load()) {
        Snapshot next;
        {
            std::unique_lock<std::mutex> lock(mutex_);
            wakeup_.wait(lock, [this] { return !queue_.empty() || !running_.load(); });

            if (!running_.load()) {
                return;
            }
            // Copied rather than popped: if the push fails the snapshot has to
            // still be at the head, and popping first would lose exactly the
            // reading a retry exists to preserve.
            next = queue_.front();
        }

        const auto outcome = pusher_.push(next);

        if (outcome.delivered) {
            {
                std::lock_guard<std::mutex> guard(mutex_);
                if (!queue_.empty()) {
                    queue_.pop_front();
                }
                ++delivered_;
            }

            if (failures > 0 && onInfo_) {
                onInfo_("Pushing to the backend again after " +
                        std::to_string(failures) + " failed attempts");
            }
            failures = 0;
            continue;
        }

        if (outcome.refused) {
            // The backend answered and said no. Retrying sends the same
            // document to the same endpoint for the same answer, and while it
            // did, the buffer behind it would fill with readings that could
            // never drain - so a misconfigured token would cost the recent
            // history as well as the rejected reading.
            {
                std::lock_guard<std::mutex> guard(mutex_);
                if (!queue_.empty()) {
                    queue_.pop_front();
                }
                ++refused_;
            }

            if (onWarning_) {
                onWarning_("The backend refused a snapshot and it has been "
                           "discarded: " + outcome.detail);
            }
            continue;
        }

        ++failures;
        if (failures <= FailuresBeforeQuieting) {
            if (onWarning_) {
                std::lock_guard<std::mutex> guard(mutex_);
                onWarning_("Could not push a snapshot (" + std::to_string(failures) +
                           " in a row, " + std::to_string(queue_.size()) +
                           " held): " + outcome.detail);
            }
        } else if (failures == FailuresBeforeQuieting + 1 && onWarning_) {
            onWarning_("Still cannot reach the backend; holding snapshots and "
                       "saying no more about it until it comes back");
        }

        // Waits on the condition variable rather than sleeping, so a stop is
        // immediate instead of taking up to the retry delay.
        std::unique_lock<std::mutex> lock(mutex_);
        wakeup_.wait_for(lock, std::chrono::milliseconds(retryDelayMs_),
                         [this] { return !running_.load(); });
    }
}

} // namespace push
