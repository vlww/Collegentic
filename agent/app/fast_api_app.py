# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import contextlib
import os
from collections.abc import AsyncIterator

import google.auth
from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from google.cloud import logging as google_cloud_logging

from app.api import router as api_router
from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.app_utils.typing import Feedback

load_dotenv()
_, project_id = google.auth.default()
logging_client = google_cloud_logging.Client()
logger = logging_client.logger(__name__)
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Built by the Docker image's frontend build stage (see Dockerfile) and
# absent in local dev, where Vite serves the frontend itself — the guard
# below keeps every route registered here a no-op until that stage exists.
FRONTEND_DIST_DIR = os.path.join(AGENT_DIR, "frontend_dist")


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built React app from the same Cloud Run service.

    Registered from inside `lifespan`, after `attach_a2a_routes`, so this
    catch-all route lands after the A2A JSON-RPC/agent-card routes in
    Starlette's route list — Starlette matches routes in registration
    order, and a route added here earlier would silently shadow them.
    """
    index_path = os.path.join(FRONTEND_DIST_DIR, "index.html")
    if not os.path.isfile(index_path):
        return

    # ADK's web UI (enabled via `web=True` below) registers its own
    # `GET /` redirect to `/dev-ui/`; drop it so `/` serves the frontend.
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == "/"
            and "GET" in getattr(route, "methods", set())
        )
    ]

    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(FRONTEND_DIST_DIR, "assets")),
        name="frontend-assets",
    )

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str) -> FileResponse:
        candidate = os.path.join(FRONTEND_DIST_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        # React Router client-side route (or a fresh load of one) — hand
        # back index.html and let the router in the browser take over.
        return FileResponse(index_path)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.agent import app as adk_app
    from app.agent import root_agent

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_app_name = adk_app.name
    await attach_a2a_routes(
        app,
        agent=root_agent,
        runner=runner,
        task_store=InMemoryTaskStore(),
        rpc_path=f"/a2a/{adk_app.name}",
    )
    _mount_frontend(app)
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    allow_origins=allow_origins,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=True,
    lifespan=lifespan,
)
app.title = "agent"
app.description = "API for interacting with the Agent agent"
app.include_router(api_router, prefix="/api")


@app.get("/api/health")
def health_check() -> dict[str, str]:
    """Lightweight liveness check for the frontend.

    Only registered at /api/health, matching every other frontend apiFetch
    call — an unprefixed /health would be dead code anyway, since ADK's own
    get_fast_api_app() already registers that path first and wins. Does not
    call Gemini or Firestore — only confirms the API process is up, so it
    stays free and instant regardless of model/credential configuration.
    """
    return {"status": "ok", "service": "collegentic-agent"}


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
