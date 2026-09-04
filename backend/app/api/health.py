from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.readiness import readiness
from app.version import VERSION

router = APIRouter()


@router.get("/health", summary="Whether this process is alive")
async def health_check():
    # Deliberately a literal, and deliberately not authenticated. It answers one
    # question — did this process respond — which is the one a supervisor needs
    # to decide whether restarting it is worth trying.
    #
    # The version rides along because this is the endpoint a deployment check
    # already calls, and "which build is actually running" is the next thing
    # asked after "is it up" — usually while something is wrong.
    return {"status": "ok", "version": VERSION}


# sync def so FastAPI runs the blocking database work in a threadpool
# instead of stalling the event loop
@router.get(
    "/ready",
    summary="Whether this process can serve requests",
    responses={503: {"description": "Not ready; the body says what is missing"}},
)
def readiness_check():
    """The other question: is the database there, is the schema current, can
    anyone log in.

    Unauthenticated, because a supervisor has no session and a check that needs
    one cannot be used before anybody has logged in. The failure details are
    instructions rather than internals — the exception goes to the log.
    """
    ready, checks = readiness()

    body = {
        "status": "ready" if ready else "not ready",
        "checks": {check.name: (check.detail or "ok") for check in checks},
    }

    if ready:
        return body

    # 503 rather than 500: nothing has gone wrong with this request, the
    # service is simply not in a state to answer others yet.
    return JSONResponse(body, status_code=503)
