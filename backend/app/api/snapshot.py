from fastapi import APIRouter, HTTPException
import httpx

from app.client import AgentClient
from app.client.errors import AgentConnectionError
from app.models.snapshot import Snapshot
from app.services.snapshot_service import SnapshotService
from config import settings

router = APIRouter()


@router.get("/snapshot", response_model=Snapshot)
async def get_snapshot():
    client = AgentClient(settings.agent_base_url)
    service = SnapshotService(client=client)
    try:
        return service.get_snapshot()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="No snapshot available yet") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AgentConnectionError as exc:
        raise HTTPException(status_code=503, detail="Unable to reach agent") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Unable to reach agent") from exc
