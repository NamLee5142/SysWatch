from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.alert import Alert, AlertList, AlertPage, AlertState
from app.repositories import AlertStore
from app.repositories.snapshot_store import to_storage_time

router = APIRouter()

MAX_LIMIT = 1000


def create_alert_store() -> AlertStore:
    return AlertStore()


# sync def so FastAPI runs the blocking database work in a threadpool
# instead of stalling the event loop
@router.get(
    "/alerts/active",
    response_model=AlertList,
    summary="Currently firing alerts, newest first",
)
def list_active_alerts(
    host: Optional[str] = Query(None, description="Limit to one host name"),
):
    records = create_alert_store().active(host_name=host)
    return AlertList(items=[Alert.from_record(record) for record in records])


# sync def so FastAPI runs the blocking database work in a threadpool
# instead of stalling the event loop
@router.get(
    "/alerts",
    response_model=AlertPage,
    summary="List alerts, newest first",
    responses={422: {"description": "Invalid time window or paging values"}},
)
def list_alerts(
    host: Optional[str] = Query(None, description="Limit to one host name"),
    state: Optional[AlertState] = Query(None, description="firing or ok"),
    rule_id: Optional[int] = Query(None, description="Limit to one rule"),
    since: Optional[datetime] = Query(None, description="Earliest trigger time, inclusive"),
    until: Optional[datetime] = Query(None, description="Latest trigger time, inclusive"),
    limit: int = Query(100, ge=1, le=MAX_LIMIT, description="Rows per page"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
):
    _validate_window(since, until)

    store = create_alert_store()
    records = store.query(
        host_name=host,
        state=state,
        rule_id=rule_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )

    return AlertPage(
        items=[Alert.from_record(record) for record in records],
        count=store.count(host_name=host, state=state, rule_id=rule_id, since=since, until=until),
    )


# sync def so FastAPI runs the blocking database work in a threadpool
# instead of stalling the event loop
@router.get(
    "/alerts/{alert_id}",
    response_model=Alert,
    summary="Fetch one alert by id",
    responses={404: {"description": "No alert with that id"}},
)
def get_alert(alert_id: int):
    record = create_alert_store().get(alert_id)

    if record is None:
        raise HTTPException(status_code=404, detail="No alert with that id")

    return Alert.from_record(record)


def _validate_window(since, until):
    if since is None or until is None:
        return

    # Normalise first: comparing an aware datetime to a naive one raises, and a
    # caller may well pass one of each.
    if to_storage_time(since) > to_storage_time(until):
        raise HTTPException(status_code=422, detail="since must not be after until")
