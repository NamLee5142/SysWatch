from fastapi import APIRouter, HTTPException, Response

from app.models.alert import AlertRule, AlertRuleCreate, AlertRuleList, AlertRuleUpdate
from app.repositories import AlertRuleStore

# The first write path on the API. It is unauthenticated, like the reads —
# acceptable while the backend only listens on localhost, but it must not reach
# a network before Phase 4 adds auth. See the CORS note in app/main.py.
router = APIRouter()


def create_rule_store() -> AlertRuleStore:
    return AlertRuleStore()


# sync def so FastAPI runs the blocking database work in a threadpool
# instead of stalling the event loop
@router.get(
    "/alert-rules",
    response_model=AlertRuleList,
    summary="List alert rules, newest first",
)
def list_alert_rules():
    records = create_rule_store().list()
    return AlertRuleList(items=[AlertRule.from_record(record) for record in records])


@router.post(
    "/alert-rules",
    response_model=AlertRule,
    status_code=201,
    summary="Create an alert rule",
    responses={422: {"description": "Invalid rule"}},
)
def create_alert_rule(payload: AlertRuleCreate):
    record = create_rule_store().create(payload)
    return AlertRule.from_record(record)


@router.put(
    "/alert-rules/{rule_id}",
    response_model=AlertRule,
    summary="Update an alert rule",
    responses={404: {"description": "No such rule"}, 422: {"description": "Invalid change"}},
)
def update_alert_rule(rule_id: int, payload: AlertRuleUpdate):
    # exclude_unset: apply only the fields the caller actually sent, so a
    # partial update does not reset everything else to a default.
    record = create_rule_store().update(rule_id, payload.model_dump(exclude_unset=True))

    if record is None:
        raise HTTPException(status_code=404, detail="No alert rule with that id")

    return AlertRule.from_record(record)


@router.delete(
    "/alert-rules/{rule_id}",
    status_code=204,
    summary="Delete an alert rule",
    responses={404: {"description": "No such rule"}},
)
def delete_alert_rule(rule_id: int):
    # Open alerts survive with rule_id set NULL; their copied fields still
    # describe what fired. See AlertRuleStore.delete.
    if not create_rule_store().delete(rule_id):
        raise HTTPException(status_code=404, detail="No alert rule with that id")

    return Response(status_code=204)
