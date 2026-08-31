from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

# "unknown" is not a failure: it is the honest answer before the poller has
# ticked, or when polling is switched off entirely. Reporting "down" there would
# put a red light on a dashboard watching a perfectly healthy agent.
AgentState = Literal["up", "down", "unknown"]


class Status(BaseModel):
    """Whether the pieces behind the dashboard are actually talking.

    `GET /health` only proves this process is up, which stays true while the
    agent has been unreachable for an hour. This answers the question a
    monitoring UI has to ask before trusting anything else it renders.
    """

    backend: Literal["ok"] = "ok"
    agent: AgentState
    pollerRunning: bool
    # Heartbeat of the loop: when it last completed a tick, successful or not.
    lastPollAt: Optional[datetime] = None
    # When a snapshot last actually arrived. Diverges from lastPollAt while the
    # agent is unreachable, which is exactly the gap worth seeing.
    lastSuccessAt: Optional[datetime] = None
    lastPollError: Optional[str] = None
