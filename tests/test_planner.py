from pathlib import Path

from autonomy_hub.services.config_loader import load_catalog
from autonomy_hub.services.planner import PlannerService
from autonomy_hub.domain.models import MissionCreateRequest


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_greenfield_planner_creates_project_shell_and_template_artifacts():
    catalog = load_catalog(CONFIG_DIR)
    planner = PlannerService(catalog)

    result = planner.plan(
        MissionCreateRequest(
            brief="Greenfield internal dashboard to coordinate frontend and backend work.",
            linked_products=["Autonomy Demo"],
            policy="safe",
        )
    )

    artifact_kinds = {artifact.kind for artifact in result.artifacts}
    assert result.mission_type == "greenfield"
    assert "project_shell" in artifact_kinds
    assert "template_selection" in artifact_kinds
    assert any(task.agent_profile_slug == "architect" for task in result.tasks)


def test_cross_repo_feature_creates_parallel_repo_owned_tasks():
    catalog = load_catalog(CONFIG_DIR)
    planner = PlannerService(catalog)

    result = planner.plan(
        MissionCreateRequest(
            brief="Cross-repo feature that touches frontend UI and backend API.",
            linked_repositories=["Eagle-Frontend", "Eagle-Backend"],
            linked_products=["Eagle"],
            policy="safe",
        )
    )

    implementer_tasks = [task for task in result.tasks if task.key.startswith("implement-")]
    scopes = {task.repo_scope[0] for task in implementer_tasks}
    assert result.mission_type == "feature"
    assert scopes == {"Eagle-Frontend", "Eagle-Backend"}
    assert len(implementer_tasks) == 2


def test_ui_refactor_single_repo_prefers_frontend_implementer():
    catalog = load_catalog(CONFIG_DIR)
    planner = PlannerService(catalog)

    result = planner.plan(
        MissionCreateRequest(
            brief="Refactor visual end-to-end para unificar screens, components y polish mobile en React Native.",
            mission_type="refactor",
            linked_repositories=["asiento-libre"],
            linked_products=["Asiento Libre"],
            policy="autopilot",
            merge_target="main",
            deploy_targets=["android-firebase-app-distribution"],
        )
    )

    implementer_tasks = [task for task in result.tasks if task.key.startswith("implement-")]
    artifact_kinds = {artifact.kind for artifact in result.artifacts}

    assert len(implementer_tasks) == 3
    assert all(task.agent_profile_slug == "frontend-implementer" for task in implementer_tasks)
    assert all(task.surface == "frontend" for task in implementer_tasks)
    assert implementer_tasks[0].key.endswith("foundation")
    assert implementer_tasks[1].depends_on == [implementer_tasks[0].key]
    assert implementer_tasks[2].depends_on == [implementer_tasks[1].key]
    assert implementer_tasks[1].key.endswith("surface-sweep")
    assert implementer_tasks[2].key.endswith("coherence-hardening")
    assert result.spec.merge_target == "main"
    assert result.spec.deploy_targets == ["android-firebase-app-distribution"]
    assert "decision_log" in artifact_kinds
