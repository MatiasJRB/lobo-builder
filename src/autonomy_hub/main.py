from __future__ import annotations

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional

from autonomy_hub.api.routes import router
from autonomy_hub.adapters.command_runner import LocalCommandRunner
from autonomy_hub.adapters.discord import DiscordWebhookAdapter
from autonomy_hub.config import Settings, get_settings
from autonomy_hub.db import build_session_factory
from autonomy_hub.services.config_loader import load_catalog
from autonomy_hub.services.graph import GraphService
from autonomy_hub.services.missions import MissionService
from autonomy_hub.services.planner import PlannerService
from autonomy_hub.services.project_context import ProjectContextResolver
from autonomy_hub.services.runner import RunnerService


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    catalog = load_catalog(resolved_settings.config_dir)
    session_factory = build_session_factory(resolved_settings.database_url)
    graph_service = GraphService(resolved_settings, session_factory, catalog)
    graph_service.seed_static_nodes()

    if resolved_settings.auto_discover_local:
        graph_service.discover_workspace()

    planner = PlannerService(catalog, settings=resolved_settings)
    mission_service = MissionService(
        settings=resolved_settings,
        session_factory=session_factory,
        catalog=catalog,
        graph_service=graph_service,
        planner=planner,
    )
    command_runner = LocalCommandRunner()
    project_context_resolver = ProjectContextResolver(resolved_settings, catalog)
    runner_service = RunnerService(
        settings=resolved_settings,
        session_factory=session_factory,
        catalog=catalog,
        mission_service=mission_service,
        project_context_resolver=project_context_resolver,
        command_runner=command_runner,
        discord_adapter=DiscordWebhookAdapter(
            resolved_settings.discord_webhook_url,
            timeout_seconds=resolved_settings.discord_webhook_timeout_seconds,
        ),
    )
    runner_service.recover_stale_runs()

    app = FastAPI(title=resolved_settings.app_name)
    templates = Jinja2Templates(directory=str(resolved_settings.config_dir.parent / "src" / "autonomy_hub" / "dashboard" / "templates"))
    static_dir = resolved_settings.config_dir.parent / "src" / "autonomy_hub" / "dashboard" / "static"

    app.state.settings = resolved_settings
    app.state.catalog = catalog
    app.state.graph_service = graph_service
    app.state.mission_service = mission_service
    app.state.runner_service = runner_service
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(router)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={},
        )

    return app


def run_dev() -> None:
    settings = get_settings()
    uvicorn.run(
        "autonomy_hub.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=True,
    )
