from pathlib import Path

from autonomy_hub.config import Settings
from autonomy_hub.services.config_loader import load_catalog
from autonomy_hub.services.planner import PlannerService
from autonomy_hub.domain.models import MissionCreateRequest


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'autonomy-test.db'}",
        workspace_root=tmp_path,
        auto_discover_local=False,
        config_dir=CONFIG_DIR,
    )


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

    assert result.mission_type == "feature"
    assert any(task.key == "planner-expand-wave-1" for task in result.tasks)
    assert not any(task.key.startswith("implement-") for task in result.tasks)
    assert result.planning_context.planning_mode == "adaptive"


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
    assert result.spec.execution_controls.deploy_enabled is True
    assert "decision_log" in artifact_kinds
    assert any(task.key == "release" for task in result.tasks)
    assert any(task.key == "deploy" for task in result.tasks)


def test_planner_inspects_local_linked_documents_and_switches_to_adaptive_mode(tmp_path: Path):
    repo = tmp_path / "backend-surface"
    docs_dir = tmp_path / "spec-input"
    docs_dir.mkdir(parents=True)
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    (docs_dir / "README.md").write_text(
        """
# Auth + UI Slice

Need schema updates, API work, and a frontend flow for onboarding.
        """.strip(),
        encoding="utf-8",
    )

    catalog = load_catalog(CONFIG_DIR)
    planner = PlannerService(catalog, settings=build_settings(tmp_path))

    result = planner.plan(
        MissionCreateRequest(
            brief="Implement onboarding across schema, API, and UI.",
            linked_repositories=["backend-surface"],
            linked_products=["Acme"],
            linked_documents=[str(docs_dir)],
            policy="safe",
        )
    )

    assert result.planning_context.planning_mode == "adaptive"
    assert any(item.inspectable for item in result.planning_context.linked_documents)
    assert any(task.key == "planner-expand-wave-1" for task in result.tasks)
    assert any(artifact.kind == "planning_context" for artifact in result.artifacts)


def test_planner_honors_explicit_execution_controls_and_deploy_task_dependencies():
    catalog = load_catalog(CONFIG_DIR)
    planner = PlannerService(catalog)

    result = planner.plan(
        MissionCreateRequest(
            brief="Ship a bounded mobile feature with manual deploy disabled.",
            linked_repositories=["asiento-libre"],
            linked_products=["Asiento Libre"],
            policy="autopilot",
            merge_target="main",
            deploy_targets=["android-firebase-app-distribution"],
            execution_controls={
                "verify_enabled": False,
                "release_enabled": True,
                "deploy_enabled": False,
                "max_runtime_hours": 2,
            },
        )
    )

    release_task = next(task for task in result.tasks if task.key == "release")
    deploy_task = next(task for task in result.tasks if task.key == "deploy")

    assert result.spec.execution_controls.verify_enabled is False
    assert result.spec.execution_controls.deploy_enabled is False
    assert result.spec.execution_controls.max_runtime_hours == 2
    assert release_task.depends_on == ["verify"]
    assert deploy_task.depends_on == ["release"]


def test_planner_reflects_repo_local_instruction_hints_in_spec_and_task_notes(tmp_path: Path):
    repo = tmp_path / "mango-app-v2"
    (repo / ".agents" / "skills" / "ui-ux-pro-max").mkdir(parents=True)
    (repo / "AGENTS.md").write_text(
        """
# Repo Instructions

Follow the repo-local conventions first.
Prefer reusable UI patterns and documented task flows.
        """.strip(),
        encoding="utf-8",
    )
    (repo / ".agents" / "skills" / "ui-ux-pro-max" / "SKILL.md").write_text(
        "# ui-ux-pro-max\n\nUse the visual system already present in the repo.\n",
        encoding="utf-8",
    )
    (repo / ".git").mkdir()

    catalog = load_catalog(CONFIG_DIR)
    planner = PlannerService(catalog, settings=build_settings(tmp_path))

    result = planner.plan(
        MissionCreateRequest(
            brief="Feature work for the Mango web app that should respect repo-local conventions.",
            linked_repositories=["mango-app-v2"],
            linked_products=["Mango"],
            policy="safe",
        )
    )

    assert any("repo-local operational guidance" in item.lower() for item in result.spec.assumptions)
    assert any("ui-ux-pro-max" in item for item in result.spec.repo_strategy)
    assert any(task.notes and "Repo-local instructions for mango-app-v2" in task.notes for task in result.tasks if task.repo_scope)
