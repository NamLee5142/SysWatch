from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.snapshot import Snapshot, SnapshotPage
from app.repositories import SnapshotStore
from app.repositories.snapshot_store import to_storage_time

router = APIRouter()

MAX_LIMIT = 1000


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
