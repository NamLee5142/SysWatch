from fastapi import APIRouter

from app.models.host import Host, HostList
from app.repositories import SnapshotStore

router = APIRouter()


def create_snapshot_store() -> SnapshotStore:
    return SnapshotStore()


# sync def so FastAPI runs the blocking database work in a threadpool
# instead of stalling the event loop
@router.get(
    "/hosts",
    response_model=HostList,
    summary="List hosts that have reported snapshots",
)
def list_hosts():
    # An empty list is a valid answer, not a 404: on a fresh database the
    # dashboard should render an empty host selector rather than an error.
    summaries = create_snapshot_store().hosts()

    return HostList(items=[Host.from_summary(summary) for summary in summaries])
