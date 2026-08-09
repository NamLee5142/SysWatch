from fastapi import APIRouter, HTTPException

from app.models.snapshot import Snapshot
from app.services.snapshot_service import SnapshotService

router = APIRouter()


@router.get("/snapshot", response_model=Snapshot)
async def get_snapshot():
    service = SnapshotService()
    try:
        return service.get_snapshot()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="No snapshot available yet") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - exercised through error handling
        raise HTTPException(status_code=503, detail="Unable to reach agent") from exc
