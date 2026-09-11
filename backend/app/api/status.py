from fastapi import APIRouter, Request

from app.models.status import Status

router = APIRouter()


@router.get(
    "/status",
    response_model=Status,
    summary="Whether the backend is reaching the agent",
)
async def get_status(request: Request):
    # Deliberately 200 even when the agent is down: this endpoint reports the
    # connection, it does not fail with it. A dashboard that got a 503 here
    # could not tell "agent unreachable" from "backend unreachable", which are
    # the two states it most needs to distinguish.
    poller = getattr(request.app.state, "poller", None)

    if poller is None:
        # Polling is disabled, so nothing is watching the agent and this process
        # genuinely does not know whether it is there.
        return Status(agent="unknown", pollerRunning=False)

    return Status(
        agent=_agent_state(poller),
        agentHost=poller.agent_host,
        pollerRunning=poller.running,
        lastPollAt=poller.last_polled_at,
        lastSuccessAt=poller.last_success_at,
        lastPollError=poller.last_error,
    )


def _agent_state(poller) -> str:
    if poller.last_polled_at is None:
        # Started, but the first tick has not landed yet.
        return "unknown"

    return "down" if poller.last_error is not None else "up"
