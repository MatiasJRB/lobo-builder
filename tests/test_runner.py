import subprocess
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from autonomy_hub.adapters.codex_exec import CodexExecResult
from autonomy_hub.adapters.command_runner import CommandResult, LocalCommandRunner
from autonomy_hub.config import Settings
from autonomy_hub.db import (
    ArtifactRecord,
    CommandExecutionRecord,
    ExecutionTaskRecord,
    MissionRecord,
    MissionRunRecord,
    build_session_factory,
    utcnow,
)
from autonomy_hub.services.config_loader import load_catalog
from autonomy_hub.services.graph import GraphService
from autonomy_hub.services.missions import MissionService
from autonomy_hub.services.planner import PlannerService
from autonomy_hub.services.project_context import ProjectContextResolver
from autonomy_hub.services.runner import RunnerService, RuntimeBudgetExceeded
from autonomy_hub.domain.models import MissionCreateRequest, ProjectInstructionHints, ProjectManifest


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


class FakeCodexExecAdapter:
    def __init__(self):
        self.prompts: list[dict[str, str]] = []

    def run(self, *, run_key, profile_slug, prompt, cwd, log_dir, add_dirs=(), model=None, reasoning_effort=None):
        log_dir.mkdir(parents=True, exist_ok=True)
        output_path = log_dir / f"{profile_slug}-last-message.txt"
        jsonl_path = log_dir / f"{profile_slug}-events.jsonl"

        self.prompts.append(
            {
                "profile_slug": profile_slug,
                "prompt": prompt,
                "cwd": str(cwd),
                "model": model,
                "reasoning_effort": reasoning_effort,
            }
        )

        if profile_slug.endswith("implementer"):
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


class FakeDiscordWebhookAdapter:
    def __init__(self):
        self.notifications: list[dict[str, str]] = []

    def enabled(self) -> bool:
        return True

    def notify_run_finished(self, *, mission, run) -> None:
        self.notifications.append(
            {
                "mission_id": mission.id,
                "run_id": run.id,
                "status": run.status,
                "error": run.last_error or "",
            }
        )


class HybridCommandRunner(LocalCommandRunner):
    def __init__(self, *, fail_on_firebase: bool = False):
        super().__init__()
        self.fail_on_firebase = fail_on_firebase

    def run(self, *, run_key, command, cwd, log_path, env=None):
        if "expo prebuild --platform android --clean --no-install" in command:
            return self._fake(command, cwd, log_path, 0, "expo prebuild ok")
        if command in {"npm install", "npm ci"}:
            expo_path = Path(cwd) / "node_modules" / "expo"
            expo_path.mkdir(parents=True, exist_ok=True)
            (expo_path / "package.json").write_text('{"name":"expo","version":"54.0.22"}', encoding="utf-8")
            return self._fake(command, cwd, log_path, 0, "dependencies installed")
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


def build_services(tmp_path: Path, *, fail_on_firebase: bool = False, discord_adapter=None):
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
    planner = PlannerService(catalog, settings=settings)
    codex_adapter = FakeCodexExecAdapter()
    mission_service = MissionService(settings, session_factory, catalog, graph_service, planner)
    runner_service = RunnerService(
        settings=settings,
        session_factory=session_factory,
        catalog=catalog,
        mission_service=mission_service,
        project_context_resolver=ProjectContextResolver(settings, catalog),
        command_runner=HybridCommandRunner(fail_on_firebase=fail_on_firebase),
        codex_adapter=codex_adapter,
        discord_adapter=discord_adapter,
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


def init_instruction_repo(tmp_path: Path, name: str = "mango-app-v2") -> Path:
    repo = tmp_path / name
    (repo / ".agents" / "skills" / "ui-ux-pro-max").mkdir(parents=True)
    (repo / "src").mkdir(parents=True)
    (repo / "package.json").write_text(
        """
{
  "name": "instruction-repo",
  "private": true,
  "scripts": {
    "test": "node -e \\"console.log('ok')\\""
  }
}
        """.strip(),
        encoding="utf-8",
    )
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
    (repo / "src" / "index.ts").write_text("export const ready = true;\n", encoding="utf-8")
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


def test_project_context_detects_repo_local_agents_and_skills_with_hint_warnings(tmp_path: Path):
    repo = init_instruction_repo(tmp_path)
    settings, _, _ = build_services(tmp_path)
    catalog = load_catalog(CONFIG_DIR)
    catalog.project_manifests[repo.name] = ProjectManifest(
        repository=repo.name,
        instruction_hints=ProjectInstructionHints(paths=["docs/AGENTS.md", "missing/skills"]),
    )
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "AGENTS.md").write_text("Secondary hinted instructions.\n", encoding="utf-8")
    resolver = ProjectContextResolver(settings, catalog)

    resolved = resolver.resolve(
        MissionCreateRequest(
            brief="Use repo-local instructions.",
            linked_repositories=[repo.name],
            linked_products=["Mango"],
            policy="safe",
        )
    )

    assert "AGENTS.md" in resolved.repo_instructions.agents_paths
    assert ".agents" in resolved.repo_instructions.agents_paths
    assert any(path.endswith("SKILL.md") for path in resolved.repo_instructions.skill_paths)
    assert "ui-ux-pro-max" in resolved.repo_instructions.skill_slugs
    assert "Follow the repo-local conventions first." in resolved.repo_instructions.summary
    assert any("root AGENTS.md takes precedence" in warning for warning in resolved.repo_instructions.warnings)
    assert any("was not found" in warning for warning in resolved.repo_instructions.warnings)


def test_runner_executes_autopilot_mission_end_to_end(tmp_path: Path):
    repo = init_asiento_repo(tmp_path)
    discord = FakeDiscordWebhookAdapter()
    _, mission_service, runner_service = build_services(tmp_path, discord_adapter=discord)

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
    assert discord.notifications == [
        {
            "mission_id": mission.id,
            "run_id": run.id,
            "status": "completed",
            "error": "",
        }
    ]


def test_clean_worktree_snapshot_surfaces_last_committed_batch(tmp_path: Path):
    init_asiento_repo(tmp_path)
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
    snapshot = mission_view.worktree_snapshot
    committed_artifacts = [
        artifact for artifact in mission_view.artifacts if artifact.kind == "diff_summary" and artifact.metadata.get("commit_sha")
    ]

    assert run.status == "completed"
    assert snapshot is not None
    assert snapshot.has_changes is False
    assert snapshot.dirty_files_count == 0
    assert snapshot.last_committed_batch is not None
    assert snapshot.last_committed_batch.commit_sha
    assert snapshot.last_committed_batch.commit_subject
    assert snapshot.last_committed_batch.files_count >= 1
    assert snapshot.last_committed_batch.changed_files
    assert "ultimo batch ya fue commiteado" in (snapshot.note or "").lower()
    assert committed_artifacts
    assert committed_artifacts[-1].metadata["files_changed"] >= 1
    assert committed_artifacts[-1].metadata["changed_files"]


def test_runner_skips_verify_and_deploy_when_controls_disable_them(tmp_path: Path):
    init_asiento_repo(tmp_path)
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
            execution_controls={
                "verify_enabled": False,
                "release_enabled": True,
                "deploy_enabled": False,
            },
        )
    )

    runner_service.start_run(mission.id)
    run = wait_for_run(runner_service, mission.id)
    mission_view = mission_service.get_mission(mission.id)
    tasks = {task.key: task for task in mission_view.execution_tasks}

    assert run.status == "completed"
    assert tasks["verify"].status == "skipped"
    assert tasks["release"].status == "completed"
    assert tasks["deploy"].status == "skipped"
    assert not any(artifact.kind == "deployment" for artifact in mission_view.artifacts)


def test_runner_injects_repo_local_instructions_and_resume_rereads_agents(tmp_path: Path):
    repo = init_instruction_repo(tmp_path)
    settings, mission_service, runner_service = build_services(tmp_path)

    mission = mission_service.create_mission(
        MissionCreateRequest(
            brief="Implement feature work while honoring repo-local AGENTS and skills.",
            mission_type="feature",
            linked_repositories=[repo.name],
            linked_products=["Mango"],
            policy="safe",
        )
    )

    runner_service.start_run(mission.id)
    first_run = wait_for_run(runner_service, mission.id)
    mission_view = mission_service.get_mission(mission.id)
    prompts = runner_service.codex_adapter.prompts

    assert first_run.status == "completed"
    assert any("Repo-local instructions:" in call["prompt"] for call in prompts)
    assert any("ui-ux-pro-max" in call["prompt"] for call in prompts)
    assert any("Follow the repo-local conventions first." in call["prompt"] for call in prompts)
    assert any(artifact.kind == "repo-instructions-summary" for artifact in mission_view.artifacts)

    (repo / "AGENTS.md").write_text(
        """
# Repo Instructions

Updated guidance for resumed runs.
Favor the changed AGENTS content over stale cached summaries.
        """.strip(),
        encoding="utf-8",
    )

    with runner_service.session_factory() as session:
        mission_record = session.get(MissionRecord, mission.id)
        latest_run = session.execute(
            select(MissionRunRecord)
            .where(MissionRunRecord.mission_id == mission.id)
            .order_by(MissionRunRecord.created_at.desc())
        ).scalar_one()
        latest_run.status = "interrupted"
        latest_run.current_task_key = None
        latest_run.completed_at = None
        mission_record.status = "interrupted"
        architect_task = session.execute(
            select(ExecutionTaskRecord).where(
                ExecutionTaskRecord.mission_id == mission.id,
                ExecutionTaskRecord.task_key == "architect-plan",
            )
        ).scalar_one()
        architect_task.status = "ready"
        session.commit()

    runner_service.start_run(mission.id, resume=True)
    resumed = wait_for_run(runner_service, mission.id)

    assert resumed.status == "completed"
    assert any("Updated guidance for resumed runs." in call["prompt"] for call in runner_service.codex_adapter.prompts)


def test_runner_expands_adaptive_wave_from_planning_context(tmp_path: Path):
    repo = init_instruction_repo(tmp_path, name="adaptive-repo")
    docs_dir = tmp_path / "mission-docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "scope.md").write_text(
        """
# Signup Slice

Touch schema, API, and UI for a single onboarding flow.
        """.strip(),
        encoding="utf-8",
    )
    _, mission_service, runner_service = build_services(tmp_path)

    mission = mission_service.create_mission(
        MissionCreateRequest(
            brief="Implement signup across schema, API, and UI.",
            mission_type="feature",
            linked_repositories=[repo.name],
            linked_products=["Adaptive"],
            linked_documents=[str(docs_dir)],
            policy="safe",
        )
    )

    assert any(task.key == "planner-expand-wave-1" for task in mission.execution_tasks)
    assert not any(task.key.startswith("implement-") for task in mission.execution_tasks)

    runner_service.start_run(mission.id)
    run = wait_for_run(runner_service, mission.id)
    mission_view = mission_service.get_mission(mission.id)
    implementation_tasks = [task for task in mission_view.execution_tasks if task.key.startswith("implement-")]

    assert run.status == "completed"
    assert implementation_tasks
    assert any(artifact.kind == "decomposition_proposal" for artifact in mission_view.artifacts)
    assert any(
        artifact.kind == "execution_graph" and artifact.title.endswith("Expanded Wave 1")
        for artifact in mission_view.artifacts
    )
    assert any(call["profile_slug"] == "architect" for call in runner_service.codex_adapter.prompts)
    assert any(call["profile_slug"].endswith("implementer") for call in runner_service.codex_adapter.prompts)
    assert all(call["model"] for call in runner_service.codex_adapter.prompts)


def test_runtime_budget_stop_interrupts_run_and_blocks_resume(tmp_path: Path):
    init_instruction_repo(tmp_path, name="budgeted-repo")
    _, mission_service, runner_service = build_services(tmp_path)

    mission = mission_service.create_mission(
        MissionCreateRequest(
            brief="Implement feature work with a strict time budget.",
            mission_type="feature",
            linked_repositories=["budgeted-repo"],
            linked_products=["Budgeted"],
            policy="safe",
            execution_controls={"max_runtime_hours": 1},
        )
    )

    stale_time = utcnow() - timedelta(hours=2)
    with runner_service.session_factory() as session:
        run = MissionRunRecord(
            mission_id=mission.id,
            status="running",
            current_task_key="architect-plan",
            branch_name=f"codex/mission-{mission.id[:8]}",
            worktree_path=str(tmp_path / "runs" / mission.id / "worktree" / "budgeted-repo"),
            started_at=stale_time,
            last_heartbeat_at=stale_time,
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
        run_id = run.id

    try:
        runner_service._check_runtime_budget(mission.id, run_id, task_key="architect-plan")
    except RuntimeBudgetExceeded as exc:
        runner_service._mark_run_interrupted(mission.id, run_id, str(exc))
    else:
        raise AssertionError("Expected runtime budget stop to interrupt the run.")

    mission_view = mission_service.get_mission(mission.id)
    tasks = {task.key: task for task in mission_view.execution_tasks}

    assert mission_view.status == "interrupted"
    assert tasks["architect-plan"].status == "ready"
    assert any(artifact.kind == "runtime_budget_stop" for artifact in mission_view.artifacts)

    try:
        runner_service.start_run(mission.id, resume=True)
    except RuntimeError as exc:
        assert "runtime budget reached" in str(exc).lower()
    else:
        raise AssertionError("Expected resume to be blocked when runtime budget is exhausted.")


def test_safe_policy_release_does_not_merge_main(tmp_path: Path):
    repo = init_instruction_repo(tmp_path, name="safe-release-repo")
    _, mission_service, runner_service = build_services(tmp_path)

    mission = mission_service.create_mission(
        MissionCreateRequest(
            brief="Implement bounded repo-local guidance support without shipping automatically.",
            mission_type="feature",
            linked_repositories=[repo.name],
            linked_products=["Lobo Builder"],
            policy="safe",
        )
    )

    runner_service.start_run(mission.id)
    run = wait_for_run(runner_service, mission.id)
    mission_view = mission_service.get_mission(mission.id)
    merge_log = subprocess.run(
        ["git", "log", "--oneline", "--merges", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )

    assert run.status == "completed"
    assert "Autopilot merge" not in merge_log.stdout
    assert any(artifact.kind == "pull_request" for artifact in mission_view.artifacts)


def test_legacy_mission_without_explicit_deploy_task_keeps_deploy_inside_release(tmp_path: Path):
    init_asiento_repo(tmp_path)
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

    with runner_service.session_factory() as session:
        deploy_task = session.execute(
            select(ExecutionTaskRecord).where(
                ExecutionTaskRecord.mission_id == mission.id,
                ExecutionTaskRecord.task_key == "deploy",
            )
        ).scalar_one()
        session.delete(deploy_task)
        session.commit()

    runner_service.start_run(mission.id)
    run = wait_for_run(runner_service, mission.id)
    mission_view = mission_service.get_mission(mission.id)

    assert run.status == "completed"
    assert not any(task.key == "deploy" for task in mission_view.execution_tasks)
    assert any(artifact.kind == "deployment" for artifact in mission_view.artifacts)


def test_runner_bootstrap_tolerates_broken_remote_when_local_base_branch_exists(tmp_path: Path):
    repo = init_instruction_repo(tmp_path, name="broken-remote-repo")
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/example/not-found.git"],
        cwd=repo,
        check=True,
    )
    _, mission_service, runner_service = build_services(tmp_path)

    mission = mission_service.create_mission(
        MissionCreateRequest(
            brief="Validate repo-local instructions without relying on remote availability.",
            mission_type="feature",
            linked_repositories=[repo.name],
            linked_products=["Mango"],
            policy="safe",
            merge_target="main",
        )
    )

    runner_service.start_run(mission.id)
    run = wait_for_run(runner_service, mission.id)
    mission_view = mission_service.get_mission(mission.id)

    assert run.status == "completed"
    assert any(artifact.kind == "repo-bootstrap-warning" for artifact in mission_view.artifacts)


def test_release_prebuild_command_becomes_non_interactive_and_version_pinned(tmp_path: Path):
    repo = init_asiento_repo(tmp_path)
    (repo / "package-lock.json").write_text(
        """
{
  "name": "asiento-libre",
  "lockfileVersion": 3,
  "packages": {
    "": { "name": "asiento-libre" },
    "node_modules/expo": { "version": "54.0.22" }
  }
}
        """.strip(),
        encoding="utf-8",
    )
    _, _, runner_service = build_services(tmp_path)

    command = runner_service._normalize_release_prebuild_command(
        "npx expo prebuild --platform android --clean --no-install",
        repo,
    )

    assert command == "npx --yes expo@54.0.22 prebuild --platform android --clean --no-install"


def test_runner_marks_failed_and_preserves_worktree_when_firebase_distribution_fails(tmp_path: Path):
    init_asiento_repo(tmp_path)
    discord = FakeDiscordWebhookAdapter()
    _, mission_service, runner_service = build_services(
        tmp_path,
        fail_on_firebase=True,
        discord_adapter=discord,
    )

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
    assert len(discord.notifications) == 1
    assert discord.notifications[0]["mission_id"] == mission.id
    assert discord.notifications[0]["run_id"] == run.id
    assert discord.notifications[0]["status"] == "failed"
    assert "firebase distribution failed" in discord.notifications[0]["error"]


def test_interrupt_resets_running_task_to_ready_for_resume(tmp_path: Path):
    init_asiento_repo(tmp_path)
    discord = FakeDiscordWebhookAdapter()
    _, mission_service, runner_service = build_services(tmp_path, discord_adapter=discord)

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
    assert discord.notifications == [
        {
            "mission_id": mission.id,
            "run_id": interrupted.id,
            "status": "interrupted",
            "error": "Interrupted by user request.",
        }
    ]

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


def test_runner_does_not_duplicate_interrupt_notifications_for_same_run(tmp_path: Path):
    init_asiento_repo(tmp_path)
    discord = FakeDiscordWebhookAdapter()
    _, mission_service, runner_service = build_services(tmp_path, discord_adapter=discord)

    mission = mission_service.create_mission(
        MissionCreateRequest(
            brief="Interrupt a running mission once and avoid duplicate notifications.",
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
        run_id = run.id

    runner_service._mark_run_interrupted(mission.id, run_id, "Interrupted by user request.")
    runner_service._mark_run_interrupted(mission.id, run_id, "Run interrupted by user.")

    assert len(discord.notifications) == 1
    assert discord.notifications[0]["mission_id"] == mission.id
    assert discord.notifications[0]["run_id"] == run_id
    assert discord.notifications[0]["status"] == "interrupted"


def test_recover_stale_run_preserves_completed_task_artifact(tmp_path: Path):
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

    stale_time = utcnow() - timedelta(days=365)
    with runner_service.session_factory() as session:
        run = MissionRunRecord(
            mission_id=mission.id,
            status="running",
            current_task_key="implement-asiento-libre-foundation",
            branch_name=f"codex/mission-{mission.id[:8]}",
            worktree_path=str(tmp_path / "runs" / mission.id / "worktree" / "asiento-libre"),
            merge_target="main",
            deploy_targets=["android-firebase-app-distribution"],
            started_at=stale_time,
            last_heartbeat_at=stale_time,
        )
        session.add(run)
        mission_record = session.get(MissionRecord, mission.id)
        mission_record.status = "running"
        task_record = session.execute(
            select(ExecutionTaskRecord).where(
                ExecutionTaskRecord.mission_id == mission.id,
                ExecutionTaskRecord.task_key == "implement-asiento-libre-foundation",
            )
        ).scalar_one()
        task_record.status = "running"
        session.add(
            CommandExecutionRecord(
                run_id=run.id,
                mission_id=mission.id,
                task_key="implement-asiento-libre-foundation",
                kind="codex",
                command="codex exec (frontend-implementer)",
                cwd=str(tmp_path / "runs" / mission.id / "worktree" / "asiento-libre"),
                status="running",
                log_path=str(tmp_path / "runs" / mission.id / "logs" / "implement-asiento-libre-foundation" / "codex.log"),
            )
        )
        session.add(
            ArtifactRecord(
                mission_id=mission.id,
                kind="diff_summary",
                title="Diff Summary · implement-asiento-libre-foundation",
                body="commit abc123\n\n    Mission batch\n",
                repo_scope=["asiento-libre"],
                attributes={
                    "task_key": "implement-asiento-libre-foundation",
                    "commit_sha": "abc123",
                    "commit_subject": "Mission batch",
                    "files_changed": 1,
                    "insertions": 1,
                    "deletions": 0,
                    "changed_files": [{"status": "M", "path": "app.tsx"}],
                },
            )
        )
        session.commit()

    runner_service.recover_stale_runs()

    with runner_service.session_factory() as session:
        run_record = session.execute(
            select(MissionRunRecord).where(MissionRunRecord.mission_id == mission.id)
        ).scalar_one()
        mission_record = session.get(MissionRecord, mission.id)
        task_record = session.execute(
            select(ExecutionTaskRecord).where(
                ExecutionTaskRecord.mission_id == mission.id,
                ExecutionTaskRecord.task_key == "implement-asiento-libre-foundation",
            )
        ).scalar_one()
        command_record = session.execute(
            select(CommandExecutionRecord).where(CommandExecutionRecord.run_id == run_record.id)
        ).scalar_one()

        assert run_record.status == "interrupted"
        assert mission_record.status == "interrupted"
        assert run_record.current_task_key is None
        assert "preserving the last completed task" in (run_record.last_error or "")
        assert task_record.status == "completed"
        assert command_record.status == "interrupted"
