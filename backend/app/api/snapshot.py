from fastapi import APIRouter, HTTPException

from app.client import AgentClient
from app.models.snapshot import Snapshot
from config import settings

router = APIRouter()


@router.get("/snapshot", response_model=Snapshot)
async def get_snapshot():
    client = AgentClient(settings.agent_base_url)
    try:
        response = client.get_snapshot()
    except Exception as exc:  # pragma: no cover - exercised through error handling
        raise HTTPException(status_code=503, detail="Unable to reach agent") from exc

    if response.status_code == 200:
        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Agent returned invalid JSON") from exc

        try:
            return Snapshot.from_payload(payload)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Agent returned an unexpected payload") from exc

    if response.status_code == 204:
        raise HTTPException(status_code=404, detail="No snapshot available yet")

    raise HTTPException(status_code=502, detail=f"Agent returned status {response.status_code}")
