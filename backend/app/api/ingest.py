"""Where a remote agent files its snapshots.

The only write path into `snapshots` that is not the poller, and the only route
in this application authenticated by a bearer token rather than a session
cookie. See docs/decisions/0001-agents-push-to-the-backend.md for why agents
push rather than being polled.
"""
import logging

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import require_agent
from app.models.auth import CurrentAgent
from app.models.ingest import IngestResult
from app.models.snapshot import Snapshot
from app.repositories import SnapshotStore

logger = logging.getLogger(__name__)

router = APIRouter()


def create_snapshot_store() -> SnapshotStore:
    return SnapshotStore()


# sync def so FastAPI runs the blocking database write in a threadpool instead
# of stalling the event loop, matching every other route that touches storage.
@router.post(
    "/ingest/snapshot",
    response_model=IngestResult,
    status_code=202,
    summary="Accept a snapshot pushed by an agent",
    responses={
        401: {"description": "No credential, or one that is unknown or revoked"},
        422: {"description": "The payload is not a snapshot"},
    },
)
def ingest_snapshot(
    request: Request,
    snapshot: Snapshot,
    agent: CurrentAgent = Depends(require_agent),
):
    """Store a snapshot under the host its credential names.

    202 rather than 201: there is no resource to give the agent a URL for, and
    the agent has no use for one. It pushed a reading; the answer is that the
    reading was taken.

    A duplicate is also a 202. `(host_name, collected_at)` is unique, so an
    agent that retried a request whose response it never saw writes nothing the
    second time - and telling it that was an error would make it retry again.
    """
    stored = create_snapshot_store().save(snapshot, host_name=agent.host_name)

    reported = snapshot.systemInfo.hostName
    if reported != agent.host_name:
        # Not an error, and not a refusal: the row is already filed under the
        # credential's host, so nothing has been forged. It is almost always a
        # deployment mistake - one machine's token copied to another - and it
        # is invisible from the dashboard, which shows only the name the token
        # gave. Neither name is a secret, so both go in the line that says so.
        logger.warning(
            "Agent for %r pushed a snapshot reporting hostname %r. The snapshot "
            "was stored under %r. Check which machine holds this token.",
            agent.host_name,
            reported,
            agent.host_name,
        )

    if stored is not None:
        evaluate_alerts(request, snapshot, agent.host_name)

    return IngestResult(hostName=agent.host_name, stored=stored is not None)


def evaluate_alerts(request, snapshot, host_name):
    """Run the alert engine over a pushed snapshot, and never fail because of it.

    The same rule the poller holds to: alerting is a side effect of collection
    and must never be the reason it stops. Here that means the agent gets its
    202 whether or not a mail server answered - an agent that retried because
    delivery failed would push the same reading forever, and each retry would
    try to deliver again.

    Already off the event loop: this route is a sync def, so FastAPI is running
    it in a threadpool worker, which is where the poller deliberately puts the
    same call.

    Skipped for a duplicate, which is an efficiency rather than a correctness
    matter and is worth stating as such: a retried push carries the same
    collectedAt and the same values, so re-evaluating it would reach the same
    conclusions and write the same numbers. What it would cost is a full pass
    over every enabled rule, plus a touch() per open alert, per retry - and an
    agent retries exactly when the backend is already having a bad time.
    """
    engine = getattr(request.app.state, "alert_engine", None)
    if engine is None:
        return

    try:
        engine.evaluate(snapshot, host_name=host_name)
    except Exception:
        logger.warning(
            "Alert evaluation failed for a snapshot pushed by %r",
            host_name,
            exc_info=True,
        )
