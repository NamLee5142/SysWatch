"""Serving the built dashboard from the backend process.

One process, one port, one origin. That removes CORS from the deployment
entirely, removes the cross-origin cookie question, and removes a second thing
to install and keep running. A reverse proxy in front for TLS is still
supported; it is no longer required for the application to work.
"""
import logging
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

INDEX = "index.html"


class SpaStaticFiles(StaticFiles):
    """Static files, plus the fallback a client-side router needs.

    The dashboard routes on `/alerts`, `/cpu` and the rest. Those paths are not
    files, so a plain static mount answers 404 and a refresh or a shared link
    lands on nothing. Falling back to index.html hands the URL to the router in
    the browser, which is what knows about them.
    """

    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
            if response.status_code != 404:
                return response
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        else:
            return response

        if not self._should_fall_back(path):
            raise HTTPException(status_code=404)

        return await super().get_response(INDEX, scope)

    @staticmethod
    def _should_fall_back(path: str) -> bool:
        # Starlette hands this path through os.path, so on Windows it arrives
        # with backslashes: "api\\no-such-endpoint". Comparing against "api/"
        # without normalising works on Linux and silently fails here, which is
        # the wrong way round for a Windows deployment.
        route = path.replace("\\", "/")

        # An unmatched /api/... is an API 404 and has to stay one. Answering it
        # with index.html would give every client bug the same symptom — a 200
        # of HTML where JSON was expected — and hide which request was wrong.
        if route == "api" or route.startswith("api/"):
            return False

        # A missing asset is a missing asset. Only extensionless paths have the
        # shape of a route, and returning HTML for a missing .js would surface
        # as a syntax error in the console rather than a 404.
        return "." not in route.rsplit("/", 1)[-1]


def mount_dashboard(app, directory: str) -> bool:
    """Mount a built dashboard at the root. Returns whether anything was mounted.

    Mounted last, so every API route is matched before it. The mount claims
    every remaining path, which is the intent: `/api` is the API and everything
    else is the application.
    """
    if not directory:
        return False

    root = Path(directory)

    if not (root / INDEX).is_file():
        # Loud, because a typo here is otherwise silent: the API keeps working
        # and the dashboard is simply absent.
        logger.warning(
            "SYSWATCH_DASHBOARD_DIR is set to %s but has no %s; "
            "serving the API only. Run 'npm run build' in dashboard/.",
            root,
            INDEX,
        )
        return False

    app.mount("/", SpaStaticFiles(directory=root, html=True), name="dashboard")
    logger.info("Serving the dashboard from %s", root)
    return True
