import subprocess
import time
from pathlib import Path

from sqlalchemy import select

from autonomy_hub.adapters.codex_exec import CodexExecResult
from autonomy_hub.adapters.command_runner import CommandResult, LocalCommandRunner
from autonomy_hub.config import Settings
from autonomy_hub.db import ExecutionTaskRecord, MissionRecord, MissionRunRecord, build_session_factory, utcnow
from autonomy_hub.services.config_loader import load_catalog
from autonomy_hub.services.graph import GraphService
from autonomy_hub.services.missions import MissionService
from autonomy_hub.services.planner import PlannerService
from autonomy_hub.services.project_context import ProjectContextResolver
from autonomy_hub.services.runner import RunnerService
from autonomy_hub.domain.models import MissionCreateRequest


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


class FakeCodexExecAdapter:
    def run(self, *, run_key, profile_slug, prompt, cwd, log_dir, add_dirs=()):
        log_dir.mkdir(parents=True, exist_ok=True)
        output_path = log_dir / f"{profile_slug}-last-message.txt"
        jsonl_path = log_dir / f"{profile_slug}-events.jsonl"

        if profile_slug == "frontend-implementer":
            target = Path(cwd) / "ui-polish-log.txt"
            target.write_text(target.read_text(encoding="utf-8") + f"\n{prompt[:80]}" if target.exists() else prompt[:80], encoding="utf-8")

        final_output = f"{profile_slug} completed"
        output_path.write_text(final_output, encoding="utf-8")
        jsonl_path.write_text('{"type":"message","text":"fake"}\n', encoding="utf-8")
        return CodexExecResult(
            profile_slug=profile_slug,
            command=f"fake-codex {profile_slug}",
            cwd=str(cwd),
            exit_code=0,
            log_path=str(jsonl_path),
            output_path=str(output_path),
            final_output=final_output,
            summary=final_output,
        )


class HybridCommandRunner(LocalCommandRunner):
    def __init__(self, *, fail_on_firebase: bool = False):
        super().__init__()
        self.fail_on_firebase = fail_on_firebase

    def run(self, *, run_key, command, cwd, log_path, env=None):
        if "npx expo prebuild --platform android --clean --no-install" in command:
            return self._fake(command, cwd, log_path, 0, "expo prebuild ok")
        if "./gradlew assembleRelease --no-daemon" in command:
            apk_path = Path(cwd) / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
            apk_path.parent.mkdir(parents=True, exist_ok=True)
            apk_path.write_text("fake apk", encoding="utf-8")
            return self._fake(command, cwd, log_path, 0, f"assembled {apk_path}")
        if "firebase appdistribution:distribute" in command:
            if self.fail_on_firebase:
                return self._fake(command, cwd, log_path, 1, "firebase distribution failed")
            return self._fake(command, cwd, log_path, 0, "firebase distribution ok")
        return super().run(run_key=run_key, command=command, cwd=cwd, log_path=log_path, env=env)

    def _fake(self, command, cwd, log_path, exit_code, summary):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(summary, encoding="utf-8")
        return CommandResult(command=command, cwd=cwd, exit_code=exit_code, log_path=str(log_path), summary=summary)


def build_services(tmp_path: Path, *, fail_on_firebase: bool = False):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'autonomy-test.db'}",
        workspace_root=tmp_path,
        runs_dir=tmp_path / "runs",
        auto_discover_local=False,
        config_dir=CONFIG_DIR,
    )
    catalog = load_catalog(CONFIG_DIR)
    session_factory = build_session_factory(settings.database_url)
    graph_service = GraphService(settings, session_factory, catalog)
    graph_service.seed_static_nodes()
    planner = PlannerService(catalog)
    mission_service = MissionService(settings, session_factory, catalog, graph_service, planner)
    runner_service = RunnerService(
        settings=settings,
        session_factory=session_factory,
        catalog=catalog,
        mission_service=mission_service,
        project_context_resolver=ProjectContextResolver(settings, catalog),
        command_runner=HybridCommandRunner(fail_on_firebase=fail_on_firebase),
        codex_adapter=FakeCodexExecAdapter(),
    )
    return settings, mission_service, runner_service


def init_asiento_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "asiento-libre"
    (repo / "context").mkdir(parents=True)
    (repo / "android").mkdir(parents=True)
    (repo / "context" / "project.json").write_text(
        """
{
  "name": "Asiento Libre Mobile",
  "defaultBranch": "main",
  "verify": { "commands": ["npm run test:unit", "npm run lint"] },
  "deploy": { "frontend": { "provider": "firebase_app_distribution" } }
}
        """.strip(),
        encoding="utf-8",
    )
    (repo / "firebase.json").write_text(
        """
{
  "appdistribution": {
    "appId": "android-app-id",
    "testers": "qa@example.com"
  }
}
        """.strip(),
        encoding="utf-8",
    )
    (repo / "package.json").write_text(
        """
{
  "name": "asiento-libre",
  "private": true,
  "scripts": {
    "test:unit": "node -e \\"console.log('unit ok')\\"",
    "lint": "node -e \\"console.log('lint ok')\\""
  }
}
        """.strip(),
        encoding="utf-8",
    )
    (repo / "RELEASE_NOTES.md").write_text("## v1\nPolish release\n", encoding="utf-8")
    (repo / "app.tsx").write_text("export const screen = 'hello';\n", encoding="utf-8")

    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    return repo


def wait_for_run(runner_service: RunnerService, mission_id: str, *, timeout_seconds: float = 20.0):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        run = runner_service.list_runs(mission_id)[0]
        if run.status in {"completed", "failed", "interrupted"}:
            return run
        time.sleep(0.1)
    raise AssertionError("Runner did not finish before timeout")


def test_project_manifest_resolution_prefers_mission_over_hub_and_repo_context(tmp_path: Path):
    init_asiento_repo(tmp_path)
    settings, _, _ = build_services(tmp_path)
    catalog = load_catalog(CONFIG_DIR)
    resolver = ProjectContextResolver(settings, catalog)

    resolved = resolver.resolve(
        MissionCreateRequest(
            brief="Polish app",
            linked_repositories=["asiento-libre"],
            linked_products=["Asiento Libre"],
            policy="autopilot",
            merge_target="release-main",
            deploy_targets=["android-firebase-app-distribution"],
        )
    )

    assert resolved.default_branch == "release-main"
    assert resolved.package_manager == "npm"
    assert resolved.verify_commands == ["npm run test:unit", "npm run lint"]
    assert resolved.release_targets == ["android-firebase-app-distribution"]
    assert resolved.android_distribution.app_id == "android-app-id"
    assert resolved.android_distribution.testers == "qa@example.com"


def test_runner_executes_autopilot_mission_end_to_end(tmp_path: Path):
    repo = init_asiento_repo(tmp_path)
    _, mission_service, runner_service = build_services(tmp_path)

    mission = mission_service.create_mission(
        MissionCreateRequest(
            brief="Refactor visual end-to-end para unificar screens y componentes mobile.",
            desired_outcome="Ship final Android build through Firebase and close in main.",
            mission_type="refactor",
            linked_repositories=["asiento-libre"],
            linked_products=["Asiento Libre"],
            policy="autopilot",
            merge_target="main",
            deploy_targets=["android-firebase-app-distribution"],
        )
    )

    runner_service.start_run(mission.id)
    run = wait_for_run(runner_service, mission.id)
    mission_view = mission_service.get_mission(mission.id)

    merge_log = subprocess.run(
        ["git", "log", "--oneline", "--merges", "main", "-1"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )

    assert run.status == "completed"
    assert mission_view.status == "completed"
    assert run.branch_name == f"codex/mission-{mission.id[:8]}"
    assert Path(run.worktree_path).exists()
    assert "Autopilot merge" in merge_log.stdout
    assert any(artifact.kind == "deployment" for artifact in mission_view.artifacts)
    assert any(artifact.kind == "release_note" for artifact in mission_view.artifacts)


def test_runner_marks_failed_and_preserves_worktree_when_firebase_distribution_fails(tmp_path: Path):
    init_asiento_repo(tmp_path)
    _, mission_service, runner_service = build_services(tmp_path, fail_on_firebase=True)

    mission = mission_service.create_mission(
        MissionCreateRequest(
            brief="Refactor visual end-to-end para unificar screens y componentes mobile.",
            desired_outcome="Ship final Android build through Firebase and close in main.",
            mission_type="refactor",
            linked_repositories=["asiento-libre"],
            linked_products=["Asiento Libre"],
            policy="autopilot",
            merge_target="main",
            deploy_targets=["android-firebase-app-distribution"],
        )
    )

    runner_service.start_run(mission.id)
    run = wait_for_run(runner_service, mission.id)
    mission_view = mission_service.get_mission(mission.id)

    assert run.status == "failed"
    assert mission_view.status == "failed"
    assert Path(run.worktree_path).exists()
    assert "firebase distribution failed" in (run.last_error or "")


def test_interrupt_resets_running_task_to_ready_for_resume(tmp_path: Path):
    init_asiento_repo(tmp_path)
    _, mission_service, runner_service = build_services(tmp_path)

    mission = mission_service.create_mission(
        MissionCreateRequest(
            brief="Refactor visual end-to-end para unificar screens y componentes mobile.",
            mission_type="refactor",
            linked_repositories=["asiento-libre"],
            linked_products=["Asiento Libre"],
            policy="autopilot",
            merge_target="main",
            deploy_targets=["android-firebase-app-distribution"],
        )
    )

    with runner_service.session_factory() as session:
        run = MissionRunRecord(
            mission_id=mission.id,
            status="running",
            current_task_key="architect-plan",
            branch_name=f"codex/mission-{mission.id[:8]}",
            worktree_path=str(tmp_path / "runs" / mission.id / "worktree" / "asiento-libre"),
            merge_target="main",
            deploy_targets=["android-firebase-app-distribution"],
            started_at=utcnow(),
            last_heartbeat_at=utcnow(),
        )
        session.add(run)
        mission_record = session.get(MissionRecord, mission.id)
        mission_record.status = "running"
        task_record = session.execute(
            select(ExecutionTaskRecord).where(
                ExecutionTaskRecord.mission_id == mission.id,
                ExecutionTaskRecord.task_key == "architect-plan",
            )
        ).scalar_one()
        task_record.status = "running"
        session.commit()

    interrupted = runner_service.interrupt_run(mission.id)

    assert interrupted.status == "interrupted"

    with runner_service.session_factory() as session:
        mission_record = session.get(MissionRecord, mission.id)
        task_record = session.execute(
            select(ExecutionTaskRecord).where(
                ExecutionTaskRecord.mission_id == mission.id,
                ExecutionTaskRecord.task_key == "architect-plan",
            )
        ).scalar_one()

        assert mission_record.status == "interrupted"
        assert task_record.status == "ready"
