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
    assert artifact_kinds == {"execution_graph", "spec"}
    assert payload["policy"]["slug"] == "safe"
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
    assert any(task["key"] == "release" for task in payload["execution_tasks"])
