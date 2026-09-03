import operator as _operator

# One callable per Operator literal (app.models.alert). It lives here, not with
# the model, because comparing a value to a threshold is evaluation, not schema.
_COMPARATORS = {
    "gt": _operator.gt,
    "gte": _operator.ge,
    "lt": _operator.lt,
    "lte": _operator.le,
}


def snapshot_metric_value(metric, snapshot):
    """The value of one metric on a live snapshot, or None if its source is absent.

    The Python twin of metric_expression() in app.repositories.snapshot_store,
    which does the same job in SQL over a stored row. Two implementations on
    purpose: this one reads the agent's nested Pydantic shape, that one a flat
    database column — the same split as Snapshot.from_payload beside from_record.

    `disk` is *used* percent, matching the chart axis, so a "disk almost full"
    rule is `disk gt 90` rather than a free-space threshold. `processes` and the
    two network metrics return None when a pre-Sprint-7 agent sent no such block;
    that is missing data, and the caller treats it as neither a breach nor a
    recovery.
    """
    if metric == "cpu":
        return snapshot.cpuInfo.usagePercent

    if metric == "memory":
        total = snapshot.memoryInfo.totalMB
        if not total:
            return None
        return 100.0 * snapshot.memoryInfo.usedMB / total

    if metric == "disk":
        total = snapshot.diskInfo.totalGB
        if not total:
            return None
        used = total - snapshot.diskInfo.freeGB
        return 100.0 * used / total

    if metric == "processes":
        if snapshot.processInfo is None:
            return None
        return float(snapshot.processInfo.count)

    if metric == "net_sent":
        if snapshot.networkInfo is None:
            return None
        # Summed to a machine total, exactly as SnapshotStore._to_record does
        # before storing it — a rule threshold is a whole-host number.
        return float(sum(nic.bytesSentPerSec for nic in snapshot.networkInfo.interfaces))

    if metric == "net_recv":
        if snapshot.networkInfo is None:
            return None
        return float(sum(nic.bytesRecvPerSec for nic in snapshot.networkInfo.interfaces))

    raise ValueError(f"Unknown metric: {metric}")


def is_violated(rule, value):
    """Whether `value` breaches `rule` under its operator.

    `value` is what snapshot_metric_value returned. None (metric absent) is not a
    breach — and the caller must not read it as a recovery either.
    """
    if value is None:
        return False

    try:
        compare = _COMPARATORS[rule.operator]
    except KeyError:
        raise ValueError(f"Unknown operator: {rule.operator}") from None

    return compare(value, rule.threshold)


def evaluate(rule, snapshot):
    """Return (value, violated) for one rule against one snapshot.

    `value` is stored on the alert whatever the outcome; `violated` drives the
    state machine. When the metric's source is absent `value` is None and
    `violated` is False, so the engine leaves that rule untouched for the tick.
    """
    value = snapshot_metric_value(rule.metric, snapshot)
    return value, is_violated(rule, value)
