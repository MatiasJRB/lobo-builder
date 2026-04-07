from pathlib import Path

from fastapi.testclient import TestClient

from autonomy_hub.config import Settings
from autonomy_hub.main import create_app


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'autonomy-test.db'}",
        workspace_root=tmp_path,
        auto_discover_local=False,
        config_dir=Path(__file__).resolve().parents[1] / "config",
    )


def test_create_mission_endpoint_persists_spec_and_execution_graph(tmp_path: Path):
    app = create_app(build_settings(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/missions",
        json={
            "brief": "Refactor a backend service without shipping to production.",
            "desired_outcome": "Leave a verified refactor branch ready for review.",
            "linked_repositories": ["service-api"],
            "linked_products": ["Service"],
            "policy": "safe",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    artifact_kinds = {artifact["kind"] for artifact in payload["artifacts"]}

    assert payload["mission_type"] == "refactor"
    assert {"execution_graph", "spec", "planning_context"}.issubset(artifact_kinds)
    assert payload["policy"]["slug"] == "safe"
    assert payload["execution_controls"]["verify_enabled"] is True
    assert payload["execution_controls"]["release_enabled"] is True
    assert any(task["key"] == "release" for task in payload["execution_tasks"])


def test_dashboard_endpoint_returns_queue_status_and_map(tmp_path: Path):
    app = create_app(build_settings(tmp_path))
    client = TestClient(app)

    client.post(
        "/api/missions",
        json={
            "brief": "Fix a broken API endpoint in a single repo.",
            "linked_repositories": ["service-api"],
            "linked_products": ["Service"],
            "policy": "safe",
        },
    )

    response = client.get("/api/dashboard")
    assert response.status_code == 200
    payload = response.json()

    assert "queue" in payload
    assert "status" in payload
    assert "map" in payload
    assert payload["queue"]


def test_dashboard_home_contains_accessible_shell(tmp_path: Path):
    app = create_app(build_settings(tmp_path))
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'href="#dashboard-main"' in html
    assert 'id="status-live-region"' in html
    assert 'id="focused-mission"' in html
    assert 'id="section-nav"' in html
    assert 'id="queue-list"' in html


def test_autopilot_mission_exposes_merge_target_and_deploy_targets(tmp_path: Path):
    app = create_app(build_settings(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/missions",
        json={
            "brief": "Polish every user-facing screen and component in the Android app.",
            "desired_outcome": "Ship a coherent build and close the cycle in main.",
            "mission_type": "refactor",
            "linked_repositories": ["asiento-libre"],
            "linked_products": ["Asiento Libre"],
            "policy": "autopilot",
            "merge_target": "main",
            "deploy_targets": ["android-firebase-app-distribution"],
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["policy"]["slug"] == "autopilot"
    assert payload["spec"]["merge_target"] == "main"
    assert payload["spec"]["deploy_targets"] == ["android-firebase-app-distribution"]
    assert payload["execution_controls"]["deploy_enabled"] is True
    assert any(task["key"] == "release" for task in payload["execution_tasks"])
    assert any(task["key"] == "deploy" for task in payload["execution_tasks"])


def test_patch_controls_updates_mission_before_first_run_and_locks_afterward(tmp_path: Path):
    app = create_app(build_settings(tmp_path))
    client = TestClient(app)

    mission = client.post(
        "/api/missions",
        json={
            "brief": "Ship Android polish with explicit deploy stage.",
            "linked_repositories": ["asiento-libre"],
            "linked_products": ["Asiento Libre"],
            "policy": "autopilot",
            "merge_target": "main",
            "deploy_targets": ["android-firebase-app-distribution"],
        },
    ).json()

    response = client.patch(
        f"/api/missions/{mission['id']}/controls",
        json={
            "verify_enabled": False,
            "deploy_enabled": False,
            "max_runtime_hours": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_controls"]["verify_enabled"] is False
    assert payload["execution_controls"]["release_enabled"] is True
    assert payload["execution_controls"]["deploy_enabled"] is False
    assert payload["execution_controls"]["max_runtime_hours"] == 3

    client.app.state.runner_service.start_run(mission["id"])

    locked = client.patch(
        f"/api/missions/{mission['id']}/controls",
        json={"release_enabled": False},
    )

    assert locked.status_code == 409


def test_local_discovery_enriches_repository_graph_metadata_with_repo_instructions(tmp_path: Path):
    repo = tmp_path / "mango-app-v2"
    (repo / ".git").mkdir(parents=True)
    (repo / ".agents" / "skills" / "ui-ux-pro-max").mkdir(parents=True)
    (repo / "AGENTS.md").write_text("Follow repo-local conventions.\n", encoding="utf-8")
    (repo / ".agents" / "skills" / "ui-ux-pro-max" / "SKILL.md").write_text(
        "# ui-ux-pro-max\n",
        encoding="utf-8",
    )

    app = create_app(build_settings(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/discovery/local",
        json={"path": str(tmp_path), "max_depth": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    repository_nodes = [node for node in payload["nodes"] if node["kind"] == "Repository" and node["name"] == "mango-app-v2"]

    assert repository_nodes
    metadata = repository_nodes[0]["metadata"]
    assert metadata["has_agents"] is True
    assert metadata["has_skills"] is True
    assert "AGENTS.md" in metadata["instruction_paths"]
    assert "ui-ux-pro-max" in metadata["skill_slugs"]
