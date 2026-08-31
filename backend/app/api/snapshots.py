from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.snapshot import Bucket, Metric, Series, SeriesPoint, Snapshot, SnapshotPage
from app.repositories import SnapshotStore
from app.repositories.snapshot_store import to_storage_time

router = APIRouter()

MAX_LIMIT = 1000
# A month of 10-second samples is ~259,000 rows. Past a few thousand points a
# chart gains no detail a screen can show, so an over-wide raw window is refused
# rather than silently truncated into a chart that lies about its range.
MAX_POINTS = 5000


def create_snapshot_store() -> SnapshotStore:
    return SnapshotStore()


# sync def so FastAPI runs the blocking database work in a threadpool
# instead of stalling the event loop
@router.get(
    "/snapshots",
    response_model=SnapshotPage,
    summary="List stored snapshots, newest first",
    responses={422: {"description": "Invalid time window or paging values"}},
)
def list_snapshots(
    host: Optional[str] = Query(None, description="Limit to one host name"),
    since: Optional[datetime] = Query(None, description="Earliest collection time, inclusive"),
    until: Optional[datetime] = Query(None, description="Latest collection time, inclusive"),
    limit: int = Query(100, ge=1, le=MAX_LIMIT, description="Rows per page"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
):
    _validate_window(since, until)

    store = create_snapshot_store()
    records = store.query(host_name=host, since=since, until=until, limit=limit, offset=offset)

    return SnapshotPage(
        items=[Snapshot.from_record(record) for record in records],
        count=store.count(host_name=host, since=since, until=until),
    )


# sync def so FastAPI runs the blocking database work in a threadpool
# instead of stalling the event loop
@router.get(
    "/snapshots/series",
    response_model=Series,
    summary="Bucketed averages for one metric, oldest first",
    responses={422: {"description": "Invalid time window, or too many points"}},
)
def snapshot_series(
    metric: Metric = Query(..., description="Which metric to plot"),
    host: Optional[str] = Query(None, description="Limit to one host name"),
    since: Optional[datetime] = Query(None, description="Earliest collection time, inclusive"),
    until: Optional[datetime] = Query(None, description="Latest collection time, inclusive"),
    bucket: Bucket = Query("hour", description="Averaging window, or raw for every sample"),
):
    _validate_window(since, until)

    store = create_snapshot_store()
    # One row over the cap is enough to know the window is too wide, and costs
    # a great deal less than counting the whole table first.
    points = store.series(
        metric=metric,
        host_name=host,
        since=since,
        until=until,
        bucket=bucket,
        limit=MAX_POINTS + 1,
    )

    if len(points) > MAX_POINTS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Window yields more than {MAX_POINTS} points. "
                "Narrow the time range or use a coarser bucket."
            ),
        )

    return Series(
        metric=metric,
        bucket=bucket,
        points=[SeriesPoint.from_point(point) for point in points],
    )


# sync def so FastAPI runs the blocking database work in a threadpool
# instead of stalling the event loop
@router.get(
    "/snapshots/latest",
    response_model=Snapshot,
    summary="Fetch the most recently stored snapshot",
    responses={404: {"description": "Nothing stored yet"}},
)
def latest_snapshot(
    host: Optional[str] = Query(None, description="Limit to one host name"),
):
    # Answered from storage, so this keeps working while the agent is down,
    # unlike GET /snapshot which asks the agent directly.
    record = create_snapshot_store().latest(host_name=host)

    if record is None:
        raise HTTPException(status_code=404, detail="No snapshot stored yet")

    return Snapshot.from_record(record)


def _validate_window(since, until):
    if since is None or until is None:
        return

    # Normalise first: comparing an aware datetime to a naive one raises, and a
    # caller may well pass one of each.
    if to_storage_time(since) > to_storage_time(until):
        raise HTTPException(status_code=422, detail="since must not be after until")
