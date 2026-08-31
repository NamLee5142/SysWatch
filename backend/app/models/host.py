from datetime import datetime

from pydantic import BaseModel


class Host(BaseModel):
    """A machine that has reported at least one snapshot."""

    hostName: str
    # The newest snapshot this host has stored, which is what makes a host look
    # stale or current in a selector.
    lastCollectedAt: datetime
    snapshotCount: int

    @classmethod
    def from_summary(cls, summary) -> "Host":
        """Build from a HostSummary.

        Taken structurally rather than by import, so the API models stay
        independent of the database layer — the same rule Snapshot follows.
        """
        return cls(
            hostName=summary.host_name,
            lastCollectedAt=summary.last_collected_at,
            snapshotCount=summary.snapshot_count,
        )


class HostList(BaseModel):
    """Every known host, most recently active first."""

    items: list[Host]
