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

    note_reported_hostname(agent.host_name, snapshot.systemInfo.hostName)

    if stored is not None:
        evaluate_alerts(request, snapshot, agent.host_name)

    return IngestResult(hostName=agent.host_name, stored=stored is not None)


# Pairs of (credential host, reported host) already mentioned. Bounded by the
# number of agents, which is the number of machines somebody installed.
_MENTIONED = set()


def note_reported_hostname(host_name, reported):
    """Say once that the payload's hostname is not the credential's.

    Once, not per push. The first version of this logged on every request and
    an agent pushing every second wrote 86,400 identical lines a day - 93% of
    the log file, measured on the first sustained run against a real backend.
    That is the same mistake httpx was making before Sprint 11 silenced it, and
    it buries the lines that mean something.

    Downgraded from a warning too, because it is usually not a problem. A token
    named "web-prod-01" issued to a machine Windows calls "DESKTOP-LMACFS6" is
    an operator naming things sensibly, and the whole reason identity comes
    from the credential is that the payload's name is not authoritative. The
    backend cannot tell that apart from a token copied to the wrong machine -
    so it says what it sees, once, and does not editorialise.
    """
    if reported == host_name:
        return

    pair = (host_name, reported)
    if pair in _MENTIONED:
        return

    # A benign race at worst: two threads may both log this once. A duplicate
    # line is cheaper than a lock on the ingestion path.
    _MENTIONED.add(pair)
    logger.info(
        "Snapshots from %r report the hostname %r. They are stored under %r, "
        "which is the host its credential names.",
        host_name,
        reported,
        host_name,
    )


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
