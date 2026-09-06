from datetime import datetime, timedelta, timezone

import pytest

from app.models.snapshot import Snapshot
from app.repositories import SnapshotStore

BASE_TIME = datetime(2026, 8, 12, 11, 15, 27, tzinfo=timezone.utc)


@pytest.fixture
def store(database):
    return SnapshotStore()


def make_snapshot(
    host_name="devbox",
    collected_at=BASE_TIME,
    cpu_usage=42.5,
    process_count=None,
    net_recv=None,
    net_sent=None,
):
    payload = {
        "collectedAt": collected_at.isoformat(),
        "cpuInfo": {"coreCount": 8, "usagePercent": cpu_usage},
        "memoryInfo": {"totalMB": 16384, "usedMB": 4096},
        "diskInfo": {"totalGB": 512, "freeGB": 120},
        "systemInfo": {"name": "Windows", "version": "11", "hostName": host_name},
    }

    if process_count is not None:
        payload["processInfo"] = {
            "count": process_count,
            "top": [{"pid": 1, "name": "top.exe", "memoryMB": 10}],
        }

    if net_recv is not None or net_sent is not None:
        payload["networkInfo"] = {
            "interfaces": [
                {
                    "name": name,
                    "bytesSent": 0,
                    "bytesRecv": 0,
                    "bytesSentPerSec": (net_sent or 0) / 2,
                    "bytesRecvPerSec": (net_recv or 0) / 2,
                }
                for name in ("Ethernet", "Wi-Fi")
            ],
        }

    return Snapshot.from_payload(payload)


def test_save_maps_every_field(store):
    record = store.save(make_snapshot())

    assert record.id is not None
    assert record.host_name == "devbox"
    assert record.cpu_core_count == 8
    assert record.cpu_usage_percent == 42.5
    assert record.mem_total_mb == 16384
    assert record.mem_used_mb == 4096
    assert record.disk_total_gb == 512
    assert record.disk_free_gb == 120
    assert record.os_name == "Windows"
    assert record.os_version == "11"


def test_saved_time_reads_back_as_utc(store):
    record = store.save(make_snapshot())

    assert record.collected_at == BASE_TIME
    assert record.collected_at.tzinfo is not None
    assert record.collected_at.utcoffset().total_seconds() == 0


def test_non_utc_time_is_converted_not_truncated(store):
    # Same instant as BASE_TIME, expressed in UTC+7.
    local = BASE_TIME.astimezone(timezone(timedelta(hours=7)))
    assert local.hour == 18

    record = store.save(make_snapshot(collected_at=local))

    assert record.collected_at == BASE_TIME
    assert record.collected_at.hour == 11


def test_saving_the_same_snapshot_twice_is_a_no_op(store):
    assert store.save(make_snapshot()) is not None
    # The poller re-reads the agent's latest snapshot on every tick; a second
    # save of the same collection must not create a second row.
    assert store.save(make_snapshot()) is None
    assert len(store.query()) == 1


def test_same_time_on_another_host_is_stored(store):
    store.save(make_snapshot(host_name="devbox"))
    store.save(make_snapshot(host_name="buildbox"))

    assert len(store.query()) == 2


def test_latest_returns_the_newest_snapshot(store):
    store.save(make_snapshot(collected_at=BASE_TIME))
    store.save(make_snapshot(collected_at=BASE_TIME + timedelta(minutes=5)))
    store.save(make_snapshot(collected_at=BASE_TIME - timedelta(minutes=5)))

    assert store.latest().collected_at == BASE_TIME + timedelta(minutes=5)


def test_latest_can_be_scoped_to_a_host(store):
    store.save(make_snapshot(host_name="devbox", collected_at=BASE_TIME))
    store.save(make_snapshot(host_name="buildbox", collected_at=BASE_TIME + timedelta(minutes=5)))

    assert store.latest(host_name="devbox").host_name == "devbox"
    assert store.latest(host_name="devbox").collected_at == BASE_TIME


def test_latest_is_none_when_empty(store):
    assert store.latest() is None
    assert store.latest(host_name="devbox") is None


def test_query_returns_newest_first(store):
    for minutes in (0, 10, 5):
        store.save(make_snapshot(collected_at=BASE_TIME + timedelta(minutes=minutes)))

    times = [record.collected_at for record in store.query()]

    assert times == sorted(times, reverse=True)


def test_query_filters_by_host(store):
    store.save(make_snapshot(host_name="devbox"))
    store.save(make_snapshot(host_name="buildbox"))

    results = store.query(host_name="buildbox")

    assert len(results) == 1
    assert results[0].host_name == "buildbox"


def test_query_filters_by_time_window_inclusively(store):
    for minutes in (0, 10, 20, 30):
        store.save(make_snapshot(collected_at=BASE_TIME + timedelta(minutes=minutes)))

    results = store.query(
        since=BASE_TIME + timedelta(minutes=10),
        until=BASE_TIME + timedelta(minutes=20),
    )

    assert [record.collected_at for record in results] == [
        BASE_TIME + timedelta(minutes=20),
        BASE_TIME + timedelta(minutes=10),
    ]


def test_query_window_accepts_non_utc_bounds(store):
    store.save(make_snapshot(collected_at=BASE_TIME))

    offset = timezone(timedelta(hours=7))
    results = store.query(
        since=(BASE_TIME - timedelta(minutes=1)).astimezone(offset),
        until=(BASE_TIME + timedelta(minutes=1)).astimezone(offset),
    )

    assert len(results) == 1


def test_query_pages_with_limit_and_offset(store):
    for minutes in range(5):
        store.save(make_snapshot(collected_at=BASE_TIME + timedelta(minutes=minutes)))

    first = store.query(limit=2)
    second = store.query(limit=2, offset=2)

    assert len(first) == 2
    assert len(second) == 2
    assert {r.collected_at for r in first}.isdisjoint({r.collected_at for r in second})
    assert first[0].collected_at == BASE_TIME + timedelta(minutes=4)
    assert second[0].collected_at == BASE_TIME + timedelta(minutes=2)


def test_count_ignores_paging(store):
    for minutes in range(5):
        store.save(make_snapshot(collected_at=BASE_TIME + timedelta(minutes=minutes)))

    assert len(store.query(limit=2)) == 2
    assert store.count() == 5


def test_count_applies_the_same_filters_as_query(store):
    save_times = (0, 10, 20)
    for minutes in save_times:
        store.save(make_snapshot(host_name="devbox", collected_at=BASE_TIME + timedelta(minutes=minutes)))
    store.save(make_snapshot(host_name="buildbox", collected_at=BASE_TIME))

    window = {
        "since": BASE_TIME + timedelta(minutes=10),
        "until": BASE_TIME + timedelta(minutes=20),
    }

    assert store.count(host_name="devbox") == 3
    assert store.count(host_name="buildbox") == 1
    assert store.count(**window) == 2
    assert store.count(host_name="devbox", **window) == len(store.query(host_name="devbox", **window))


def test_count_is_zero_when_empty(store):
    assert store.count() == 0


def test_prune_removes_only_snapshots_before_the_cutoff(store):
    for days in (10, 5, 1):
        store.save(make_snapshot(collected_at=BASE_TIME - timedelta(days=days)))

    removed = store.prune(BASE_TIME - timedelta(days=6))

    assert removed == 1
    remaining = [record.collected_at for record in store.query()]
    assert remaining == [BASE_TIME - timedelta(days=1), BASE_TIME - timedelta(days=5)]


def test_prune_is_exclusive_at_the_cutoff(store):
    store.save(make_snapshot(collected_at=BASE_TIME))

    # A snapshot exactly at the cutoff is inside the retention window.
    assert store.prune(BASE_TIME) == 0
    assert store.count() == 1


def test_prune_returns_zero_when_nothing_is_old_enough(store):
    store.save(make_snapshot(collected_at=BASE_TIME))

    assert store.prune(BASE_TIME - timedelta(days=30)) == 0


def test_prune_normalises_a_non_utc_cutoff(store):
    store.save(make_snapshot(collected_at=BASE_TIME - timedelta(hours=2)))

    # Same instant as BASE_TIME, expressed in UTC+7. Treating it as a naive
    # local time would delete the wrong rows.
    cutoff = BASE_TIME.astimezone(timezone(timedelta(hours=7)))

    assert store.prune(cutoff) == 1


def test_query_is_empty_when_nothing_matches(store):
    store.save(make_snapshot())

    assert store.query(host_name="nowhere") == []
    assert store.query(since=BASE_TIME + timedelta(days=1)) == []


def test_save_stores_process_count_and_the_top_list(store):
    record = store.save(make_snapshot(process_count=240))

    assert record.process_count == 240
    assert record.process_top == [{"pid": 1, "name": "top.exe", "memoryMB": 10}]


def test_save_sums_the_per_interface_rates_and_keeps_the_breakdown(store):
    record = store.save(make_snapshot(net_recv=1000.0, net_sent=400.0))

    # Two interfaces at half each: the scalar columns carry the machine total,
    # the JSON column keeps the per-interface rows.
    assert record.net_bytes_recv_per_sec == 1000.0
    assert record.net_bytes_sent_per_sec == 400.0
    assert [nic["name"] for nic in record.network_interfaces] == ["Ethernet", "Wi-Fi"]


def test_save_leaves_the_new_columns_null_when_the_agent_sends_nothing(store):
    record = store.save(make_snapshot())

    assert record.process_count is None
    assert record.process_top is None
    assert record.net_bytes_recv_per_sec is None
    assert record.network_interfaces is None


def test_series_averages_the_process_count(store):
    for minutes, count in ((0, 100), (20, 120), (40, 140)):
        store.save(make_snapshot(collected_at=BASE_TIME + timedelta(minutes=minutes), process_count=count))

    points = store.series(metric="processes", bucket="hour")

    assert [point.value for point in points] == [120.0]


def test_series_reports_network_throughput_in_raw_bytes(store):
    store.save(make_snapshot(net_recv=2048.0))

    points = store.series(metric="net_recv", bucket="raw")

    assert [point.value for point in points] == [2048.0]


def test_series_skips_rows_that_never_carried_the_metric(store):
    store.save(make_snapshot(collected_at=BASE_TIME, process_count=None))
    store.save(make_snapshot(collected_at=BASE_TIME + timedelta(minutes=1), process_count=200))

    points = store.series(metric="processes", bucket="raw")

    # The first row has a NULL process_count — nothing to plot, not a zero.
    assert [point.value for point in points] == [200.0]


# --- the bucket goes into SQL text ------------------------------------------


def test_an_unknown_bucket_is_refused(store):
    """The bucket name is interpolated into SQL, so it has to be a known one.

    Unreachable through the API, which types the parameter as a Literal and
    rejects anything else with a 422 before the store is called. This is the
    store keeping its own promise instead of relying on that.
    """
    with pytest.raises(ValueError, match="Unknown bucket"):
        store.series("cpu", bucket="hour'); DROP TABLE snapshots; --")

    assert store.count() == 0  # still there


def test_every_offered_bucket_is_accepted(store):
    """BUCKETS and the API's Bucket type have to agree, or one of them lies."""
    from app.models.snapshot import Bucket
    from app.repositories.snapshot_store import BUCKETS, RAW_BUCKET

    offered = set(Bucket.__args__)

    assert offered == set(BUCKETS) | {RAW_BUCKET}
