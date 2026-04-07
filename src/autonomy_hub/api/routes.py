from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from autonomy_hub.domain.models import (
    DiscoveryRequest,
    MissionCreateRequest,
    MissionExecutionControlsUpdateRequest,
)


router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/dashboard")
def dashboard(request: Request):
    return request.app.state.mission_service.dashboard_snapshot()


@router.get("/api/missions")
def list_missions(request: Request):
    return request.app.state.mission_service.list_missions()


@router.post("/api/missions")
def create_mission(payload: MissionCreateRequest, request: Request):
    try:
        return request.app.state.mission_service.create_mission(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/missions/{mission_id}")
def get_mission(mission_id: str, request: Request):
    try:
        return request.app.state.mission_service.get_mission(mission_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mission not found") from exc


@router.post("/api/missions/{mission_id}/run")
def run_mission(mission_id: str, request: Request):
    try:
        return request.app.state.runner_service.start_run(mission_id, resume=False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mission not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/missions/{mission_id}/resume")
def resume_mission(mission_id: str, request: Request):
    try:
        return request.app.state.runner_service.start_run(mission_id, resume=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mission not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/missions/{mission_id}/interrupt")
def interrupt_mission(mission_id: str, request: Request):
    try:
        return request.app.state.runner_service.interrupt_run(mission_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mission not found") from exc


@router.patch("/api/missions/{mission_id}/controls")
def patch_mission_controls(mission_id: str, payload: MissionExecutionControlsUpdateRequest, request: Request):
    try:
        return request.app.state.mission_service.update_mission_controls(mission_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Mission not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/missions/{mission_id}/runs")
def mission_runs(mission_id: str, request: Request):
    return request.app.state.mission_service.list_runs(mission_id)


@router.get("/api/missions/{mission_id}/logs")
def mission_logs(mission_id: str, request: Request):
    return request.app.state.mission_service.mission_logs(mission_id)


@router.get("/api/graph")
def graph_snapshot(request: Request):
    return request.app.state.graph_service.snapshot()


@router.post("/api/discovery/local")
def discover_local(request_payload: DiscoveryRequest, request: Request):
    path = Path(request_payload.path).expanduser() if request_payload.path else None
    return request.app.state.graph_service.discover_workspace(
        path=path,
        max_depth=request_payload.max_depth,
    )
