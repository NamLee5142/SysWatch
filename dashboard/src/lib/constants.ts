// Sprint 6 locked decision: refresh model is polling at 5s. The backend's own
// poller (SnapshotPoller) only ticks every 10s by default, so polling faster
// than that gains nothing; slower would show data staler than the backend
// already has.
export const POLL_INTERVAL_MS = 5000
