from pydantic import BaseModel


class IngestResult(BaseModel):
    """What an agent is told about the snapshot it pushed.

    Deliberately not the stored row. The agent already has the data - echoing
    it back is a payload's worth of network per push to tell the sender what it
    just said.

    `stored` is false when the row already existed, which is a success: an
    agent that retried after a timeout it could not distinguish from a failure
    did the right thing, and the response says so rather than reporting an
    error the agent would retry again.
    """

    hostName: str
    stored: bool
