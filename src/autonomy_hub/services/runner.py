from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from subprocess import run as subprocess_run
from threading import Lock, Thread, current_thread
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen
from typing import Optional

from sqlalchemy import select

from autonomy_hub.adapters.codex_exec import CodexExecAdapter
from autonomy_hub.adapters.command_runner import CommandResult, LocalCommandRunner
from autonomy_hub.adapters.discord import DiscordWebhookAdapter
from autonomy_hub.adapters.git import GitWorktreePlan, branch_exists, build_worktree_plan, has_remote, primary_remote
from autonomy_hub.config import Settings
from autonomy_hub.db import ArtifactRecord, CommandExecutionRecord, ExecutionTaskRecord, MissionRecord, MissionRunRecord, utcnow
from autonomy_hub.domain.models import (
    ArtifactPayload,
    CommandExecutionView,
    ConfigCatalog,
    ExecutionTaskSpec,
    MissionCreateRequest,
    MissionExecutionControls,
    MissionLogsView,
    MissionRunView,
    MissionSpec,
    MissionView,
)
from autonomy_hub.services.missions import MissionService
from autonomy_hub.services.project_context import ProjectContextResolver, ResolvedProjectContext


class MissionExecutionError(RuntimeError):
    pass


class RunInterrupted(MissionExecutionError):
    pass


class RuntimeBudgetExceeded(RunInterrupted):
    pass


logger = logging.getLogger(__name__)


class RunnerService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory,
        catalog: ConfigCatalog,
        mission_service: MissionService,
        project_context_resolver: ProjectContextResolver,
        command_runner: Optional[LocalCommandRunner] = None,
        codex_adapter: Optional[CodexExecAdapter] = None,
        discord_adapter: Optional[DiscordWebhookAdapter] = None,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.catalog = catalog
        self.mission_service = mission_service
        self.project_context_resolver = project_context_resolver
        self.command_runner = command_runner or LocalCommandRunner()
        self.codex_adapter = codex_adapter or CodexExecAdapter(settings, self.command_runner)
        self.discord_adapter = discord_adapter or DiscordWebhookAdapter(
            settings.discord_webhook_url,
            timeout_seconds=settings.discord_webhook_timeout_seconds,
        )
        self._threads: dict[str, Thread] = {}
        self._lock = Lock()

    def recover_stale_runs(self) -> None:
        stale_before = utcnow() - timedelta(seconds=self.settings.runner_heartbeat_timeout_seconds)
        with self.session_factory() as session:
            runs = session.execute(
                select(MissionRunRecord).where(MissionRunRecord.status.in_(["running", "verifying", "releasing"]))
            ).scalars()
            touched_missions: set[str] = set()
            for run in runs:
                heartbeat = self._coerce_utc(run.last_heartbeat_at or run.updated_at)
                if heartbeat and heartbeat < stale_before:
                    mission = session.get(MissionRecord, run.mission_id)
                    recovered = self._reconcile_stale_run(session, run)
                    if self._all_tasks_completed(session, run.mission_id):
                        run.status = "completed"
                        run.current_task_key = None
                        run.completed_at = run.completed_at or utcnow()
                        run.last_error = None
                        if mission:
                            mission.status = "completed"
                            touched_missions.add(mission.id)
                        continue

                    run.status = "interrupted"
                    run.current_task_key = None
                    run.last_error = (
                        "Recovered stale run after preserving the last completed task."
                        if recovered
                        else "Marked interrupted after stale heartbeat on startup."
                    )
                    if mission:
                        mission.status = "interrupted"
                        touched_missions.add(mission.id)
            if touched_missions:
                session.commit()

    def start_run(self, mission_id: str, *, resume: bool = False) -> MissionRunView:
        with self._lock:
            existing_thread = self._threads.get(mission_id)
            if existing_thread and not existing_thread.is_alive():
                self._threads.pop(mission_id, None)
                existing_thread = None
            if existing_thread and existing_thread.is_alive():
                latest_run = self._latest_run(mission_id)
                if latest_run and latest_run.status not in {"completed", "failed", "interrupted"}:
                    return latest_run

        with self.session_factory() as session:
            mission = session.get(MissionRecord, mission_id)
            if not mission:
                raise KeyError(mission_id)
            spec = MissionSpec.model_validate(mission.spec_payload or {})
            controls = spec.execution_controls.normalized(has_deploy_targets=bool(spec.deploy_targets))
            budget_elapsed_hours = self._runtime_budget_elapsed_hours(session, mission_id)
            if self._runtime_budget_reached(controls, budget_elapsed_hours):
                raise RuntimeError(
                    f"Mission runtime budget reached ({budget_elapsed_hours:.2f}h / {controls.max_runtime_hours}h)."
                )

            latest_run = session.execute(
                select(MissionRunRecord)
                .where(MissionRunRecord.mission_id == mission_id)
                .order_by(MissionRunRecord.created_at.desc())
            ).scalars().first()

            if resume and latest_run:
                if latest_run.completed_at:
                    run = MissionRunRecord(
                        mission_id=mission_id,
                        status="running",
                        branch_name=latest_run.branch_name,
                        worktree_path=latest_run.worktree_path,
                        merge_target=latest_run.merge_target or spec.merge_target,
                        deploy_targets=latest_run.deploy_targets or spec.deploy_targets,
                        started_at=utcnow(),
                        last_heartbeat_at=utcnow(),
                    )
                    session.add(run)
                else:
                    run = latest_run
                    run.status = "running"
                    run.last_error = None
                    if not run.started_at:
                        run.started_at = utcnow()
                    run.completed_at = None
            else:
                run = MissionRunRecord(
                    mission_id=mission_id,
                    status="running",
                    merge_target=(mission.spec_payload or {}).get("merge_target"),
                    deploy_targets=(mission.spec_payload or {}).get("deploy_targets", []),
                    started_at=utcnow(),
                    last_heartbeat_at=utcnow(),
                )
                session.add(run)

            mission.status = "running"
            session.commit()
            run_id = run.id

        thread = Thread(target=self._execute_run, args=(mission_id, run_id), daemon=True)
        with self._lock:
            self._threads[mission_id] = thread
        thread.start()
        return self._latest_run(mission_id)

    def interrupt_run(self, mission_id: str) -> MissionRunView:
        run = self._latest_run(mission_id)
        if not run:
            raise KeyError(mission_id)

        self.command_runner.interrupt(run.id)
        self._mark_run_interrupted(mission_id, run.id, "Interrupted by user request.")
        return self._latest_run(mission_id)

    def list_runs(self, mission_id: str) -> list[MissionRunView]:
        with self.session_factory() as session:
            records = session.execute(
                select(MissionRunRecord)
                .where(MissionRunRecord.mission_id == mission_id)
                .order_by(MissionRunRecord.created_at.desc())
            ).scalars()
            return [self._assemble_run(session, record) for record in records]

    def mission_logs(self, mission_id: str) -> MissionLogsView:
        runs = self.list_runs(mission_id)
        with self.session_factory() as session:
            records = session.execute(
                select(CommandExecutionRecord)
                .where(CommandExecutionRecord.mission_id == mission_id)
                .order_by(CommandExecutionRecord.created_at.desc())
            ).scalars()
            commands = [self._assemble_command(record) for record in records]
        return MissionLogsView(mission_id=mission_id, runs=runs, commands=commands)

    def _execute_run(self, mission_id: str, run_id: str) -> None:
        try:
            mission = self.mission_service.get_mission(mission_id)
            payload = MissionCreateRequest(
                brief=mission.brief,
                desired_outcome=mission.desired_outcome,
                mission_type=mission.mission_type,
                linked_repositories=mission.linked_repositories,
                linked_products=mission.linked_products,
                linked_documents=mission.linked_documents,
                policy=mission.policy.slug,
                merge_target=mission.spec.merge_target,
                deploy_targets=mission.spec.deploy_targets,
            )
            project = self.project_context_resolver.resolve(payload)
            self._record_repo_instruction_summary(mission.id, project)
            self._ensure_worktree(run_id, mission, project)

            while True:
                self._touch_run(run_id)
                self._fail_if_interrupted(run_id)
                self._check_runtime_budget(mission.id, run_id)
                next_task = self._promote_and_pick_next_task(mission_id)
                if not next_task:
                    self._finish_run(mission_id, run_id)
                    return
                self._run_task(mission_id, run_id, mission, next_task, project)
        except RunInterrupted as exc:
            self._mark_run_interrupted(mission_id, run_id, str(exc))
        except MissionExecutionError as exc:
            self._mark_run_failed(mission_id, run_id, str(exc))
        except Exception as exc:  # pragma: no cover - safety net
            self._mark_run_failed(mission_id, run_id, f"Unhandled runner error: {exc}")
        finally:
            with self._lock:
                if self._threads.get(mission_id) is current_thread():
                    self._threads.pop(mission_id, None)

    def _run_task(
        self,
        mission_id: str,
        run_id: str,
        mission: MissionView,
        task: ExecutionTaskSpec,
        project: ResolvedProjectContext,
    ) -> None:
        mission = self.mission_service.get_mission(mission_id)
        self._set_run_state(run_id, current_task_key=task.key, status=self._status_for_task(task.key))
        skip_reason = self._skip_reason(mission, task)
        if skip_reason:
            self._skip_task(mission_id, run_id, task, skip_reason)
            return

        self._set_task_status(mission_id, task.key, "running")

        if task.key == "architect-plan":
            self._run_architect(mission, task, project, run_id)
        elif self._is_planner_expand_task(task):
            self._run_planner_expand(mission, task, run_id)
        elif task.key.startswith("implement-"):
            self._run_implementer(mission, task, project, run_id)
        elif task.key == "verify":
            self._run_verify(mission, task, project, run_id)
        elif task.key == "release":
            self._run_release(mission, task, project, run_id)
        elif task.key == "deploy":
            self._run_deploy(mission, task, project, run_id)
        else:
            raise MissionExecutionError(f"Runner does not know how to execute task '{task.key}'.")

        self._set_task_status(mission_id, task.key, "completed")

    @staticmethod
    def _is_planner_expand_task(task: ExecutionTaskSpec) -> bool:
        if task.key.startswith("planner-expand-wave"):
            return True
        return task.agent_profile_slug == "planner" and task.surface == "planning"

    def _run_architect(
        self,
        mission: MissionView,
        task: ExecutionTaskSpec,
        project: ResolvedProjectContext,
        run_id: str,
    ) -> None:
        prompt = self._render_prompt(mission, task, project)
        result = self._run_codex_logged(
            mission.id,
            run_id,
            task.key,
            task.agent_profile_slug,
            cwd=self.settings.config_dir.parent,
            prompt=prompt,
            add_dirs=[project.repo_path],
        )
        self._ensure_command_success(result.exit_code, task.key, result.summary)
        self._create_artifact(
            mission.id,
            ArtifactPayload(
                kind="decision_log",
                title="Operational Run Decision Log",
                body=result.final_output or result.summary,
                repo_scope=[project.repository],
                metadata={"task_key": task.key, "profile": task.agent_profile_slug},
            ),
        )

    def _run_planner_expand(
        self,
        mission: MissionView,
        task: ExecutionTaskSpec,
        run_id: str,
    ) -> None:
        mission = self.mission_service.get_mission(mission.id)
        planning_context = self.mission_service.planner.planning_context_from_artifacts(mission.artifacts)
        if not planning_context:
            raise MissionExecutionError("Adaptive planner expansion requires a planning_context artifact.")

        request = self._mission_request(mission)
        proposal = self.mission_service.planner.build_decomposition_proposal(
            request,
            mission_type=mission.mission_type,
            spec=mission.spec,
            planning_context=planning_context,
        )
        implementation_tasks = self.mission_service.planner.implementation_tasks_from_proposal(proposal)
        if implementation_tasks:
            self._append_execution_tasks(mission.id, implementation_tasks)
            self._update_task_dependencies(
                mission.id,
                task_key="verify",
                depends_on=[item.key for item in implementation_tasks],
            )
            refreshed_mission = self.mission_service.get_mission(mission.id)
            self._create_artifact(
                mission.id,
                ArtifactPayload(
                    kind="execution_graph",
                    title="Execution Graph · Expanded Wave 1",
                    body=self.mission_service.planner._execution_graph_body(refreshed_mission.execution_tasks),
                    repo_scope=mission.linked_repositories,
                    metadata={"task_count": len(refreshed_mission.execution_tasks), "source": task.key},
                ),
            )

        self._create_artifact(
            mission.id,
            ArtifactPayload(
                kind="decomposition_proposal",
                title="Decomposition Proposal",
                body=self.mission_service.planner.decomposition_proposal_body(proposal),
                repo_scope=mission.linked_repositories,
                metadata={"proposal": proposal.model_dump(mode="json"), "task_key": task.key},
            ),
        )

    @staticmethod
    def _mission_request(mission: MissionView) -> MissionCreateRequest:
        return MissionCreateRequest(
            brief=mission.brief,
            desired_outcome=mission.desired_outcome,
            mission_type=mission.mission_type,
            linked_repositories=mission.linked_repositories,
            linked_products=mission.linked_products,
            linked_documents=mission.linked_documents,
            policy=mission.policy.slug,
            merge_target=mission.spec.merge_target,
            deploy_targets=mission.spec.deploy_targets,
            execution_controls=mission.execution_controls,
        )

    def _run_implementer(
        self,
        mission: MissionView,
        task: ExecutionTaskSpec,
        project: ResolvedProjectContext,
        run_id: str,
    ) -> None:
        prompt = self._render_prompt(mission, task, project)
        result = self._run_codex_logged(
            mission.id,
            run_id,
            task.key,
            task.agent_profile_slug,
            cwd=Path(self._require_run(run_id).worktree_path),
            prompt=prompt,
            add_dirs=[self.settings.config_dir.parent, project.repo_path],
        )
        self._ensure_command_success(result.exit_code, task.key, result.summary)
        worktree_path = Path(self._require_run(run_id).worktree_path)
        dirty = self._run_shell_logged(
            mission.id,
            run_id,
            task.key,
            "shell",
            "git status --short",
            cwd=worktree_path,
        )
        self._ensure_command_success(dirty.exit_code, task.key, dirty.summary)
        artifact_body = "No code changes were committed for this task."
        artifact_metadata = {"task_key": task.key, "no_changes": True}
        if dirty.summary.strip():
            self._run_shell_logged(mission.id, run_id, task.key, "git", "git add -A", cwd=worktree_path)
            commit_message = f"Mission {mission.id[:8]}: {task.key}"
            commit = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                f"git commit -m '{commit_message}'",
                cwd=worktree_path,
            )
            self._ensure_command_success(commit.exit_code, task.key, commit.summary)
            diff_summary = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                "git show --stat --format=medium HEAD",
                cwd=worktree_path,
            )
            self._ensure_command_success(diff_summary.exit_code, task.key, diff_summary.summary)
            name_status = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                "git show --name-status --format= HEAD",
                cwd=worktree_path,
            )
            self._ensure_command_success(name_status.exit_code, task.key, name_status.summary)
            shortstat = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                "git show --shortstat --format= HEAD",
                cwd=worktree_path,
            )
            self._ensure_command_success(shortstat.exit_code, task.key, shortstat.summary)
            commit_sha = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                "git rev-parse HEAD",
                cwd=worktree_path,
            )
            self._ensure_command_success(commit_sha.exit_code, task.key, commit_sha.summary)
            commit_subject = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                "git log -1 --pretty=%s",
                cwd=worktree_path,
            )
            self._ensure_command_success(commit_subject.exit_code, task.key, commit_subject.summary)
            artifact_body = diff_summary.summary
            artifact_metadata = self._build_commit_diff_metadata(
                task_key=task.key,
                diff_stat=diff_summary.summary,
                shortstat=shortstat.summary,
                name_status=name_status.summary,
                commit_sha=commit_sha.summary.strip(),
                commit_subject=commit_subject.summary.strip(),
            )
        self._create_artifact(
            mission.id,
            ArtifactPayload(
                kind="diff_summary",
                title=f"Diff Summary · {task.key}",
                body=artifact_body,
                repo_scope=[project.repository],
                metadata=artifact_metadata,
            ),
        )

    def _run_verify(
        self,
        mission: MissionView,
        task: ExecutionTaskSpec,
        project: ResolvedProjectContext,
        run_id: str,
    ) -> None:
        worktree_path = Path(self._require_run(run_id).worktree_path)
        verification_sections: list[str] = []
        for command in project.verify_commands:
            result = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "verify",
                command,
                cwd=worktree_path,
            )
            self._ensure_command_success(result.exit_code, task.key, result.summary)
            verification_sections.append(f"$ {command}\n{result.summary}")

        prompt = self._render_prompt(mission, task, project, extra_sections=verification_sections)
        review = self._run_codex_logged(
            mission.id,
            run_id,
            task.key,
            task.agent_profile_slug,
            cwd=worktree_path,
            prompt=prompt,
            add_dirs=[self.settings.config_dir.parent],
        )
        self._ensure_command_success(review.exit_code, task.key, review.summary)
        body = "\n\n".join(verification_sections + [review.final_output or review.summary])
        self._create_artifact(
            mission.id,
            ArtifactPayload(
                kind="verification_report",
                title="Verification Report",
                body=body,
                repo_scope=[project.repository],
                metadata={"task_key": task.key},
            ),
        )

    def _run_release(
        self,
        mission: MissionView,
        task: ExecutionTaskSpec,
        project: ResolvedProjectContext,
        run_id: str,
    ) -> None:
        run = self._require_run(run_id)
        if mission.policy.slug == "safe":
            self._run_safe_release_handoff(mission, task, project, run_id, run)
            return
        merge_target = run.merge_target or project.default_branch
        release_repo = project.repo_path
        self._ensure_release_repo_ready(mission.id, run_id, task.key, release_repo, merge_target)

        remote = primary_remote(str(project.repo_path))
        if remote:
            fetch = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                f"git fetch {remote} --prune",
                cwd=release_repo,
            )
            self._ensure_command_success(fetch.exit_code, task.key, fetch.summary)
            sync_main = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                f"git merge --ff-only {remote}/{merge_target}",
                cwd=release_repo,
            )
            self._ensure_command_success(sync_main.exit_code, task.key, sync_main.summary)

        merge_commit = self._run_shell_logged(
            mission.id,
            run_id,
            task.key,
            "git",
            f"git merge --no-ff {run.branch_name} -m 'Autopilot merge for mission {mission.id}'",
            cwd=release_repo,
        )
        self._ensure_command_success(merge_commit.exit_code, task.key, merge_commit.summary)

        if remote and mission.policy.can_push:
            push = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                f"git push {remote} {merge_target}",
                cwd=release_repo,
            )
            self._ensure_command_success(push.exit_code, task.key, push.summary)

        explicit_deploy_stage = self._mission_has_explicit_deploy_stage(mission)
        distribution = project.android_distribution
        if not explicit_deploy_stage and "android-firebase-app-distribution" in project.release_targets:
            if not distribution or not distribution.app_id or not distribution.testers:
                raise MissionExecutionError("Android Firebase distribution is configured but appId/testers are missing.")

            self._deploy_android_firebase_distribution(
                mission=mission,
                task_key=task.key,
                project=project,
                run_id=run_id,
                release_repo=release_repo,
                distribution=distribution,
            )

        release_note_body = self._release_notes_body(release_repo / (distribution.release_notes_path if distribution else "RELEASE_NOTES.md"))
        self._create_artifact(
            mission.id,
            ArtifactPayload(
                kind="release_note",
                title="Autopilot Release Note",
                body=release_note_body,
                repo_scope=[project.repository],
                metadata={"task_key": task.key, "merge_target": merge_target},
            ),
        )
        self._create_artifact(
            mission.id,
            ArtifactPayload(
                kind="merge",
                title="Autopilot Merge Summary",
                body=merge_commit.summary,
                repo_scope=[project.repository],
                metadata={"task_key": task.key, "merge_target": merge_target, "branch_name": run.branch_name},
            ),
        )

    def _run_safe_release_handoff(
        self,
        mission: MissionView,
        task: ExecutionTaskSpec,
        project: ResolvedProjectContext,
        run_id: str,
        run: MissionRunView,
    ) -> None:
        release_repo = Path(run.worktree_path or project.repo_path)
        branch_name = run.branch_name
        if not branch_name:
            raise MissionExecutionError("Safe policy release requires an execution branch to prepare the PR handoff.")

        remote = primary_remote(str(release_repo))
        if not remote:
            self._create_safe_release_gate_artifact(
                mission=mission,
                task=task,
                project=project,
                run=run,
                reason="No git remote was configured for this repository, so the PR handoff stays manual.",
            )
            return

        if mission.policy.can_push:
            push = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                f"git push -u {remote} {branch_name}",
                cwd=release_repo,
            )
            if push.exit_code != 0:
                self._create_safe_release_gate_artifact(
                    mission=mission,
                    task=task,
                    project=project,
                    run=run,
                    reason=(
                        f"Branch push to '{remote}' could not be completed automatically. "
                        f"Runner output: {push.summary or 'no summary available'}"
                    ),
                )
                return

        if not mission.policy.can_open_pr:
            self._create_safe_release_gate_artifact(
                mission=mission,
                task=task,
                project=project,
                run=run,
                reason="Mission policy does not allow opening a pull request automatically.",
            )
            return

        merge_target = run.merge_target or project.default_branch
        pr = self._create_or_find_safe_pull_request(
            mission=mission,
            project=project,
            release_repo=release_repo,
            branch_name=branch_name,
            merge_target=merge_target,
        )
        self._create_artifact(
            mission.id,
            ArtifactPayload(
                kind="pull_request",
                title="Safe Policy Pull Request",
                body=(
                    f"Pull request opened against `{merge_target}`.\n"
                    f"URL: {pr['url']}\n"
                    f"Branch: {branch_name}\n"
                    f"Repository: {pr['repository']}"
                ),
                repo_scope=[project.repository],
                uri=pr["url"],
                metadata={
                    "task_key": task.key,
                    "policy": mission.policy.slug,
                    "branch_name": branch_name,
                    "merge_target": merge_target,
                    "pr_number": pr["number"],
                    "repository": pr["repository"],
                },
            ),
        )

        review_request = self._request_copilot_review(
            release_repo=release_repo,
            repository=pr["repository"],
            pr_number=pr["number"],
        )
        self._create_artifact(
            mission.id,
            ArtifactPayload(
                kind="review_request",
                title="Copilot Review Request",
                body=review_request["message"],
                repo_scope=[project.repository],
                uri=pr["url"],
                metadata={
                    "task_key": task.key,
                    "policy": mission.policy.slug,
                    "branch_name": branch_name,
                    "merge_target": merge_target,
                    "pr_number": pr["number"],
                    "repository": pr["repository"],
                    "status": review_request["status"],
                    "reviewer": review_request["reviewer"],
                },
            ),
        )

    def _create_safe_release_gate_artifact(
        self,
        *,
        mission: MissionView,
        task: ExecutionTaskSpec,
        project: ResolvedProjectContext,
        run: MissionRunView,
        reason: str,
    ) -> None:
        self._create_artifact(
            mission.id,
            ArtifactPayload(
                kind="pull_request",
                title="Safe Policy Release Gate",
                body=(
                    f"Mission policy '{mission.policy.slug}' keeps merge and deploy disabled.\n"
                    f"Branch '{run.branch_name}' remains isolated in worktree '{run.worktree_path}'.\n"
                    f"{reason}"
                ),
                repo_scope=[project.repository],
                metadata={"task_key": task.key, "policy": mission.policy.slug, "branch_name": run.branch_name},
            ),
        )

    def _create_or_find_safe_pull_request(
        self,
        *,
        mission: MissionView,
        project: ResolvedProjectContext,
        release_repo: Path,
        branch_name: str,
        merge_target: str,
    ) -> dict[str, object]:
        remote = primary_remote(str(release_repo))
        if not remote:
            raise MissionExecutionError("Could not determine the remote used for the safe release handoff.")

        remote_url = self._git_remote_url(release_repo, remote)
        owner, repo = self._parse_github_repository(remote_url)
        token = self._github_api_token(remote_url)
        existing = self._find_pull_request(owner=owner, repo=repo, branch_name=branch_name, merge_target=merge_target, token=token)
        if existing:
            return existing

        title = self._safe_pull_request_title(mission)
        body = self._safe_pull_request_body(mission, project=project, branch_name=branch_name, merge_target=merge_target)
        payload = {
            "title": title,
            "head": branch_name,
            "base": merge_target,
            "body": body,
            "draft": False,
        }
        response = self._github_api_request(
            f"https://api.github.com/repos/{owner}/{repo}/pulls",
            token=token,
            method="POST",
            payload=payload,
        )
        return {
            "number": response["number"],
            "url": response["html_url"],
            "repository": response["base"]["repo"]["full_name"],
        }

    def _request_copilot_review(self, *, release_repo: Path, repository: str, pr_number: int) -> dict[str, str]:
        remote = primary_remote(str(release_repo))
        if not remote:
            return {
                "status": "skipped",
                "reviewer": "Copilot",
                "message": "Copilot review request skipped because no git remote was available.",
            }

        remote_url = self._git_remote_url(release_repo, remote)
        owner, repo = self._parse_github_repository(remote_url)
        token = self._github_api_token(remote_url)
        try:
            self._github_api_request(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers",
                token=token,
                method="POST",
                payload={"reviewers": ["copilot-pull-request-reviewer[bot]"]},
            )
        except MissionExecutionError as exc:
            return {
                "status": "failed",
                "reviewer": "Copilot",
                "message": f"Copilot review request could not be completed automatically: {exc}",
            }

        return {
            "status": "requested",
            "reviewer": "Copilot",
            "message": f"Copilot review requested on PR #{pr_number} in {repository}.",
        }

    def _find_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        branch_name: str,
        merge_target: str,
        token: str,
    ) -> dict[str, object] | None:
        query = quote(f"{owner}:{branch_name}", safe=":")
        response = self._github_api_request(
            (
                f"https://api.github.com/repos/{owner}/{repo}/pulls"
                f"?state=open&head={query}&base={quote(merge_target, safe='')}"
            ),
            token=token,
        )
        if not response:
            return None
        pull = response[0]
        return {
            "number": pull["number"],
            "url": pull["html_url"],
            "repository": pull["base"]["repo"]["full_name"],
        }

    def _safe_pull_request_title(self, mission: MissionView) -> str:
        title = mission.brief.strip()
        return title if len(title) <= 120 else f"{title[:117].rstrip()}..."

    def _safe_pull_request_body(
        self,
        mission: MissionView,
        *,
        project: ResolvedProjectContext,
        branch_name: str,
        merge_target: str,
    ) -> str:
        lines = [
            "## Mission",
            f"- Summary: {mission.brief}",
            f"- Desired outcome: {mission.desired_outcome or 'n/a'}",
            f"- Scope: {project.repository}",
            "",
            "## Branch Handoff",
            f"- Head: `{branch_name}`",
            f"- Base: `{merge_target}`",
            f"- Policy: `{mission.policy.slug}`",
        ]

        diff_summaries = [artifact for artifact in mission.artifacts if artifact.kind == "diff_summary"]
        if diff_summaries:
            lines.extend(["", "## Included Changes"])
            for artifact in diff_summaries:
                title = artifact.title.replace("Diff Summary · ", "")
                lines.append(f"- {title}")

        verification = next((artifact for artifact in reversed(mission.artifacts) if artifact.kind == "verification_report"), None)
        if verification:
            lines.extend(["", "## Verification", verification.body])

        lines.extend(
            [
                "",
                "## Notes",
                "- This PR was opened by the safe-policy release handoff.",
                "- Review/merge remain outside the mission runner.",
            ]
        )
        return "\n".join(lines)

    def _git_remote_url(self, repo_path: Path, remote: str) -> str:
        completed = subprocess_run(
            ["git", "-C", str(repo_path), "remote", "get-url", remote],
            capture_output=True,
            text=True,
            check=False,
        )
        remote_url = completed.stdout.strip()
        if completed.returncode != 0 or not remote_url:
            raise MissionExecutionError(f"Could not resolve git remote URL for '{remote}'.")
        return remote_url

    def _parse_github_repository(self, remote_url: str) -> tuple[str, str]:
        owner_repo: str | None = None
        if remote_url.startswith("git@"):
            try:
                host_part, owner_repo = remote_url.split(":", 1)
            except ValueError as exc:
                raise MissionExecutionError(f"Unsupported git remote format: {remote_url}") from exc
            host = host_part.split("@", 1)[1]
        else:
            parsed = urlparse(remote_url)
            host = parsed.hostname or ""
            owner_repo = parsed.path.lstrip("/")

        if host != "github.com":
            raise MissionExecutionError(f"Safe release PR creation currently supports github.com remotes only; got '{host}'.")

        owner_repo = owner_repo.removesuffix(".git")
        if owner_repo.count("/") < 1:
            raise MissionExecutionError(f"Could not parse owner/repository from remote '{remote_url}'.")
        owner, repo = owner_repo.split("/", 1)
        return owner, repo

    def _github_api_token(self, remote_url: str) -> str:
        parsed = urlparse(remote_url)
        if parsed.scheme in {"http", "https"} and parsed.username:
            return unquote(parsed.username)

        gh = subprocess_run(["gh", "auth", "token"], capture_output=True, text=True, check=False)
        token = gh.stdout.strip()
        if gh.returncode == 0 and token:
            return token

        raise MissionExecutionError(
            "Could not resolve a GitHub token for safe-policy PR creation. "
            "Use an HTTPS remote with a token or authenticate gh."
        )

    def _github_api_request(
        self,
        url: str,
        *,
        token: str,
        method: str = "GET",
        payload: dict[str, object] | None = None,
    ):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "lobo-builder-runner",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8")
            try:
                message = json.loads(details).get("message", details)
            except json.JSONDecodeError:
                message = details or str(exc)
            raise MissionExecutionError(f"GitHub API {method} {url} failed: {message}") from exc

    def _run_deploy(
        self,
        mission: MissionView,
        task: ExecutionTaskSpec,
        project: ResolvedProjectContext,
        run_id: str,
    ) -> None:
        release_repo = project.repo_path
        distribution = project.android_distribution

        if "android-firebase-app-distribution" in project.release_targets:
            if not distribution or not distribution.app_id or not distribution.testers:
                raise MissionExecutionError("Android Firebase distribution is configured but appId/testers are missing.")

            self._deploy_android_firebase_distribution(
                mission=mission,
                task_key=task.key,
                project=project,
                run_id=run_id,
                release_repo=release_repo,
                distribution=distribution,
            )

    def _deploy_android_firebase_distribution(
        self,
        *,
        mission: MissionView,
        task_key: str,
        project: ResolvedProjectContext,
        run_id: str,
        release_repo: Path,
        distribution,
    ) -> None:
        install_command = self._release_dependency_install_command(project.package_manager, release_repo)
        if install_command:
            install = self._run_shell_logged(
                mission.id,
                run_id,
                task_key,
                "deps",
                install_command,
                cwd=release_repo,
            )
            self._ensure_command_success(install.exit_code, task_key, install.summary)

        prebuild_command = self._normalize_release_prebuild_command(distribution.prebuild_command, release_repo)
        prebuild = self._run_shell_logged(
            mission.id,
            run_id,
            task_key,
            "android-build",
            prebuild_command,
            cwd=release_repo,
        )
        self._ensure_command_success(prebuild.exit_code, task_key, prebuild.summary)

        assemble = self._run_shell_logged(
            mission.id,
            run_id,
            task_key,
            "android-build",
            distribution.assemble_command,
            cwd=release_repo / "android",
        )
        self._ensure_command_success(assemble.exit_code, task_key, assemble.summary)

        release_notes = self._release_notes_body(release_repo / distribution.release_notes_path)
        distribute = self._run_shell_logged(
            mission.id,
            run_id,
            task_key,
            "firebase",
            (
                f"firebase appdistribution:distribute {self._shell_quote(release_repo / distribution.apk_path)} "
                f"--app {self._shell_quote(distribution.app_id)} "
                f"--testers {self._shell_quote(distribution.testers)} "
                f"--release-notes {self._shell_quote(release_notes)}"
                + (
                    f" --project {self._shell_quote(distribution.firebase_project)}"
                    if distribution.firebase_project
                    else ""
                )
            ),
            cwd=release_repo,
        )
        self._ensure_command_success(distribute.exit_code, task_key, distribute.summary)

        self._create_artifact(
            mission.id,
            ArtifactPayload(
                kind="deployment",
                title="Android Firebase Distribution",
                body=distribute.summary,
                repo_scope=[project.repository],
                metadata={
                    "task_key": task_key,
                    "target": "android-firebase-app-distribution",
                    "apk_path": str(release_repo / distribution.apk_path),
                },
            ),
        )

    def _ensure_worktree(self, run_id: str, mission: MissionView, project: ResolvedProjectContext) -> None:
        run = self._require_run(run_id)
        if run.worktree_path and Path(run.worktree_path).exists():
            return

        branch_name = run.branch_name or f"codex/mission-{mission.id[:8]}"
        worktree_path = self.settings.runs_dir / mission.id / "worktree" / project.repository
        plan: GitWorktreePlan = build_worktree_plan(
            str(project.repo_path),
            branch_name,
            worktree_path=str(worktree_path),
            base_branch=project.default_branch,
        )
        for command in plan.commands:
            result = self._run_shell_logged(mission.id, run_id, "runner-bootstrap", "git", command, cwd=project.repo_path)
            if (
                result.exit_code != 0
                and "fetch --all --prune" in command
                and branch_exists(str(project.repo_path), project.default_branch)
            ):
                self._create_artifact(
                    mission.id,
                    ArtifactPayload(
                        kind="repo-bootstrap-warning",
                        title="Worktree Bootstrap Warning",
                        body=(
                            f"Remote fetch failed while preparing '{project.repository}', "
                            f"but local branch '{project.default_branch}' exists so bootstrap continued.\n"
                            f"{result.summary}"
                        ),
                        repo_scope=[project.repository],
                        metadata={"task_key": "runner-bootstrap", "repository": project.repository},
                    ),
                )
                continue
            self._ensure_command_success(result.exit_code, "runner-bootstrap", result.summary)
        with self.session_factory() as session:
            record = session.get(MissionRunRecord, run_id)
            if record:
                record.branch_name = branch_name
                record.worktree_path = plan.worktree_path
                record.merge_target = record.merge_target or project.default_branch
                record.last_heartbeat_at = utcnow()
            session.commit()
        self._create_artifact(
            mission.id,
            ArtifactPayload(
                kind="branch",
                title="Mission Branch",
                body=f"Branch: {branch_name}\nWorktree: {plan.worktree_path}",
                repo_scope=[project.repository],
                metadata={"branch_name": branch_name, "worktree_path": plan.worktree_path},
            ),
        )

    def _reconcile_stale_run(self, session, run: MissionRunRecord) -> bool:
        recovered = False
        commands = session.execute(
            select(CommandExecutionRecord).where(
                CommandExecutionRecord.run_id == run.id,
                CommandExecutionRecord.status == "running",
            )
        ).scalars()
        for command in commands:
            if command.exit_code is not None:
                command.status = "completed" if command.exit_code == 0 else "failed"
            else:
                command.status = "interrupted"
                command.summary = command.summary or "Marked interrupted after stale heartbeat recovery."

        if not run.current_task_key:
            return recovered

        task = session.execute(
            select(ExecutionTaskRecord).where(
                ExecutionTaskRecord.mission_id == run.mission_id,
                ExecutionTaskRecord.task_key == run.current_task_key,
            )
        ).scalar_one_or_none()
        if not task:
            return recovered

        if task.status == "running":
            if self._task_has_completion_evidence(session, task):
                task.status = "completed"
                recovered = True
            else:
                task.status = "ready"
        return recovered

    def _task_has_completion_evidence(self, session, task: ExecutionTaskRecord) -> bool:
        expected_artifacts = set(task.expected_artifacts or [])
        if not expected_artifacts:
            return False

        artifacts = session.execute(
            select(ArtifactRecord)
            .where(ArtifactRecord.mission_id == task.mission_id)
            .order_by(ArtifactRecord.created_at.desc())
        ).scalars()
        for artifact in artifacts:
            attributes = artifact.attributes or {}
            if artifact.kind in expected_artifacts and attributes.get("task_key") == task.task_key:
                return True
        return False

    def _all_tasks_completed(self, session, mission_id: str) -> bool:
        tasks = session.execute(
            select(ExecutionTaskRecord).where(ExecutionTaskRecord.mission_id == mission_id)
        ).scalars()
        task_list = list(tasks)
        return bool(task_list) and all(task.status in {"completed", "skipped"} for task in task_list)

    def _render_prompt(
        self,
        mission: MissionView,
        task: ExecutionTaskSpec,
        project: ResolvedProjectContext,
        *,
        extra_sections: Optional[list[str]] = None,
    ) -> str:
        template = self.catalog.runner_prompts.get(task.agent_profile_slug) or self.catalog.runner_prompts.get(
            "default",
            "Mission:\n{{MISSION_SPEC}}\n\nTask:\n{{TASK_JSON}}\n\nProject:\n{{PROJECT_JSON}}\n",
        )
        artifacts = [
            artifact
            for artifact in mission.artifacts
            if not artifact.repo_scope or project.repository in artifact.repo_scope
        ]
        replacements = {
            "{{MISSION_SPEC}}": mission.spec.model_dump_json(indent=2),
            "{{TASK_JSON}}": task.model_dump_json(indent=2),
            "{{PROJECT_JSON}}": json.dumps(
                {
                    "repository": project.repository,
                    "repo_path": str(project.repo_path),
                    "default_branch": project.default_branch,
                    "verify_commands": project.verify_commands,
                    "release_targets": project.release_targets,
                },
                indent=2,
            ),
            "{{ARTIFACTS}}": json.dumps(
                [artifact.model_dump(mode="json") for artifact in artifacts],
                indent=2,
            ),
            "{{REPO_INSTRUCTIONS}}": self._repo_instructions_prompt_block(project),
            "{{LINKED_DOCUMENTS}}": "\n".join(mission.linked_documents) or "(none)",
            "{{EXTRA_SECTIONS}}": "\n\n".join(extra_sections or []),
        }
        rendered = template
        for token, value in replacements.items():
            rendered = rendered.replace(token, value)
        return rendered.strip()

    def _repo_instructions_prompt_block(self, project: ResolvedProjectContext) -> str:
        repo_instructions = project.repo_instructions
        payload = {
            "repository": project.repository,
            "agents_paths": repo_instructions.agents_paths,
            "skill_paths": repo_instructions.skill_paths,
            "skill_slugs": repo_instructions.skill_slugs,
            "summary": repo_instructions.summary or "No repo-local instructions detected.",
            "warnings": repo_instructions.warnings,
            "policy_override": "Mission policy always wins if repo-local instructions conflict with allowed actions.",
        }
        return json.dumps(payload, indent=2)

    def _record_repo_instruction_summary(self, mission_id: str, project: ResolvedProjectContext) -> None:
        repo_instructions = project.repo_instructions
        if not (
            repo_instructions.agents_paths
            or repo_instructions.skill_paths
            or repo_instructions.warnings
            or repo_instructions.summary
        ):
            return

        body_lines = [
            f"Repository: {project.repository}",
            "Agents paths:",
            *([f"- {path}" for path in repo_instructions.agents_paths] or ["- none detected"]),
            "Skill paths:",
            *([f"- {path}" for path in repo_instructions.skill_paths] or ["- none detected"]),
            "Skill slugs:",
            *([f"- {slug}" for slug in repo_instructions.skill_slugs] or ["- none detected"]),
            f"Summary: {repo_instructions.summary or 'No repo-local instruction summary available.'}",
            "Warnings:",
            *([f"- {warning}" for warning in repo_instructions.warnings] or ["- none"]),
        ]
        self._create_artifact(
            mission_id,
            ArtifactPayload(
                kind="repo-instructions-summary",
                title=f"Repo-local Instructions · {project.repository}",
                body="\n".join(body_lines),
                repo_scope=[project.repository],
                metadata={
                    "repository": project.repository,
                    "agents_paths": repo_instructions.agents_paths,
                    "skill_paths": repo_instructions.skill_paths,
                    "skill_slugs": repo_instructions.skill_slugs,
                    "warnings": repo_instructions.warnings,
                },
            ),
        )

    def _skip_reason(self, mission: MissionView, task: ExecutionTaskSpec) -> Optional[str]:
        controls = mission.execution_controls.normalized(has_deploy_targets=bool(mission.spec.deploy_targets))

        if task.key == "verify" and not controls.verify_enabled:
            return "Verify stage disabled from mission controls."
        if task.key == "release" and not controls.release_enabled:
            return "Release stage disabled from mission controls."
        if task.key == "deploy":
            if not self._mission_has_explicit_deploy_stage(mission):
                return "Legacy mission keeps deployment inside the release stage."
            if not controls.release_enabled:
                return "Deploy skipped because release is disabled from mission controls."
            if not controls.deploy_enabled:
                return "Deploy stage disabled from mission controls."
            if not mission.policy.can_deploy:
                return f"Mission policy '{mission.policy.slug}' does not allow deploy actions."
        return None

    def _skip_task(self, mission_id: str, run_id: str, task: ExecutionTaskSpec, reason: str) -> None:
        self._create_artifact(
            mission_id,
            ArtifactPayload(
                kind="decision_log",
                title=f"Stage skipped · {task.key}",
                body=reason,
                repo_scope=task.repo_scope,
                metadata={"task_key": task.key, "skip_reason": reason},
            ),
        )
        self._set_task_status(mission_id, task.key, "skipped")
        self._set_run_state(run_id, current_task_key=None, status="running")

    @staticmethod
    def _mission_has_explicit_deploy_stage(mission: MissionView) -> bool:
        return any(task.key == "deploy" for task in mission.execution_tasks)

    def _promote_and_pick_next_task(self, mission_id: str) -> Optional[ExecutionTaskSpec]:
        with self.session_factory() as session:
            task_records = list(
                session.execute(
                    select(ExecutionTaskRecord)
                    .where(ExecutionTaskRecord.mission_id == mission_id)
                    .order_by(ExecutionTaskRecord.created_at.asc())
                ).scalars()
            )
            completed = {task.task_key for task in task_records if task.status in {"completed", "skipped"}}
            for task in task_records:
                if task.status in {"queued", "blocked"} and all(dep in completed for dep in (task.depends_on or [])):
                    task.status = "ready"
            session.commit()
            next_task = next((task for task in task_records if task.status == "ready"), None)
            if not next_task:
                return None
            return ExecutionTaskSpec(
                key=next_task.task_key,
                title=next_task.title,
                agent_profile_slug=next_task.agent_profile_slug,
                repo_scope=next_task.repo_scope or [],
                surface=next_task.surface,
                status=next_task.status,
                acceptance_criteria=next_task.acceptance_criteria or [],
                expected_artifacts=next_task.expected_artifacts or [],
                depends_on=next_task.depends_on or [],
                notes=next_task.notes,
            )

    def _finish_run(self, mission_id: str, run_id: str) -> None:
        should_notify = False
        with self.session_factory() as session:
            mission = session.get(MissionRecord, mission_id)
            run = session.get(MissionRunRecord, run_id)
            if run and run.completed_at is not None and run.status in {"completed", "failed", "interrupted"}:
                return
            if mission:
                mission.status = "completed"
            if run:
                should_notify = True
                run.status = "completed"
                run.current_task_key = None
                run.completed_at = utcnow()
                run.last_heartbeat_at = utcnow()
            session.commit()
        if should_notify:
            self._notify_terminal_state(mission_id, run_id)

    def _mark_run_failed(self, mission_id: str, run_id: str, error: str) -> None:
        should_notify = False
        with self.session_factory() as session:
            mission = session.get(MissionRecord, mission_id)
            run = session.get(MissionRunRecord, run_id)
            if run and run.completed_at is not None and run.status in {"completed", "failed", "interrupted"}:
                return
            if run and run.current_task_key:
                self._transition_current_task(
                    session,
                    mission_id=mission_id,
                    task_key=run.current_task_key,
                    next_status="failed",
                )
            if mission:
                mission.status = "failed"
            if run:
                should_notify = True
                run.status = "failed"
                run.current_task_key = None
                run.last_error = error
                run.completed_at = utcnow()
                run.last_heartbeat_at = utcnow()
            session.commit()
        if should_notify:
            self._notify_terminal_state(mission_id, run_id)

    def _mark_run_interrupted(self, mission_id: str, run_id: str, error: str) -> None:
        should_notify = False
        with self.session_factory() as session:
            mission = session.get(MissionRecord, mission_id)
            run = session.get(MissionRunRecord, run_id)
            if run and run.completed_at is not None and run.status in {"completed", "failed", "interrupted"}:
                return
            if run and run.current_task_key:
                self._transition_current_task(
                    session,
                    mission_id=mission_id,
                    task_key=run.current_task_key,
                    next_status="ready",
                )
            if mission:
                mission.status = "interrupted"
            if run:
                should_notify = True
                run.status = "interrupted"
                run.current_task_key = None
                run.last_error = error
                run.completed_at = utcnow()
                run.last_heartbeat_at = utcnow()
            session.commit()
        if should_notify:
            self._notify_terminal_state(mission_id, run_id)

    def _set_task_status(self, mission_id: str, task_key: str, status: str) -> None:
        with self.session_factory() as session:
            self._transition_current_task(session, mission_id=mission_id, task_key=task_key, next_status=status)
            session.commit()

    def _append_execution_tasks(self, mission_id: str, tasks: list[ExecutionTaskSpec]) -> None:
        with self.session_factory() as session:
            existing_keys = {
                record.task_key
                for record in session.execute(
                    select(ExecutionTaskRecord).where(ExecutionTaskRecord.mission_id == mission_id)
                ).scalars()
            }
            for task in tasks:
                if task.key in existing_keys:
                    continue
                session.add(
                    ExecutionTaskRecord(
                        mission_id=mission_id,
                        task_key=task.key,
                        title=task.title,
                        agent_profile_slug=task.agent_profile_slug,
                        repo_scope=task.repo_scope,
                        surface=task.surface,
                        status=task.status,
                        acceptance_criteria=task.acceptance_criteria,
                        expected_artifacts=task.expected_artifacts,
                        depends_on=task.depends_on,
                        notes=task.notes,
                    )
                )
            session.commit()

    def _update_task_dependencies(self, mission_id: str, *, task_key: str, depends_on: list[str]) -> None:
        with self.session_factory() as session:
            record = session.execute(
                select(ExecutionTaskRecord).where(
                    ExecutionTaskRecord.mission_id == mission_id,
                    ExecutionTaskRecord.task_key == task_key,
                )
            ).scalar_one_or_none()
            if not record:
                return
            record.depends_on = depends_on
            if record.status in {"ready", "queued"}:
                record.status = "blocked"
            session.commit()

    def _notify_terminal_state(self, mission_id: str, run_id: str) -> None:
        if not self.discord_adapter or not self.discord_adapter.enabled():
            return

        try:
            mission = self.mission_service.get_mission(mission_id)
            with self.session_factory() as session:
                record = session.get(MissionRunRecord, run_id)
                if not record:
                    return
                run = self._assemble_run(session, record)
            if run.status not in {"completed", "failed", "interrupted"}:
                return
            self.discord_adapter.notify_run_finished(mission=mission, run=run)
        except Exception as exc:  # pragma: no cover - notifications must not break mission closure
            logger.warning("Discord notification failed for mission %s run %s: %s", mission_id, run_id, exc)

    def _transition_current_task(self, session, *, mission_id: str, task_key: str, next_status: str) -> None:
        task = session.execute(
            select(ExecutionTaskRecord).where(
                ExecutionTaskRecord.mission_id == mission_id,
                ExecutionTaskRecord.task_key == task_key,
            )
        ).scalar_one()
        task.status = next_status

    @staticmethod
    def _coerce_utc(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _set_run_state(self, run_id: str, *, current_task_key: Optional[str], status: str) -> None:
        with self.session_factory() as session:
            run = session.get(MissionRunRecord, run_id)
            mission = session.get(MissionRecord, run.mission_id) if run else None
            if run:
                run.current_task_key = current_task_key
                run.status = status
                run.last_heartbeat_at = utcnow()
            if mission:
                mission.status = status
            session.commit()

    def _touch_run(self, run_id: str) -> None:
        with self.session_factory() as session:
            run = session.get(MissionRunRecord, run_id)
            if run:
                run.last_heartbeat_at = utcnow()
            session.commit()

    def _require_run(self, run_id: str) -> MissionRunView:
        with self.session_factory() as session:
            record = session.get(MissionRunRecord, run_id)
            if not record:
                raise MissionExecutionError(f"Run '{run_id}' not found.")
            return self._assemble_run(session, record)

    def _latest_run(self, mission_id: str) -> Optional[MissionRunView]:
        with self.session_factory() as session:
            record = session.execute(
                select(MissionRunRecord)
                .where(MissionRunRecord.mission_id == mission_id)
                .order_by(MissionRunRecord.created_at.desc())
            ).scalars().first()
            return self._assemble_run(session, record) if record else None

    def _run_shell_logged(
        self,
        mission_id: str,
        run_id: str,
        task_key: str,
        kind: str,
        command: str,
        *,
        cwd: Path,
    ) -> CommandResult:
        execution = self._create_command_execution(mission_id, run_id, task_key, kind, command, cwd)
        result = self.command_runner.run(
            run_key=run_id,
            command=command,
            cwd=str(cwd),
            log_path=Path(execution.log_path),
        )
        self._complete_command_execution(execution.id, result.exit_code, result.summary)
        self._touch_run(run_id)
        self._check_runtime_budget(mission_id, run_id, task_key=task_key)
        return result

    def _run_codex_logged(
        self,
        mission_id: str,
        run_id: str,
        task_key: str,
        profile_slug: str,
        *,
        cwd: Path,
        prompt: str,
        add_dirs: list[Path],
    ):
        profile = self.catalog.agent_profiles[profile_slug]
        execution = self._create_command_execution(
            mission_id,
            run_id,
            task_key,
            "codex",
            f"codex exec ({profile_slug}{f' model={profile.model}' if profile.model else ''})",
            cwd,
        )
        result = self.codex_adapter.run(
            run_key=run_id,
            profile_slug=profile_slug,
            prompt=prompt,
            cwd=cwd,
            log_dir=Path(execution.log_path).parent,
            add_dirs=add_dirs,
            model=profile.model,
            reasoning_effort=profile.reasoning_effort,
        )
        summary = result.summary or result.final_output
        self._complete_command_execution(execution.id, result.exit_code, summary, log_path=result.log_path)
        self._touch_run(run_id)
        self._check_runtime_budget(mission_id, run_id, task_key=task_key)
        return result

    def _create_command_execution(
        self,
        mission_id: str,
        run_id: str,
        task_key: str,
        kind: str,
        command: str,
        cwd: Path,
    ) -> CommandExecutionView:
        log_dir = self.settings.runs_dir / mission_id / "logs" / task_key
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{kind}-{utcnow().strftime('%Y%m%d%H%M%S%f')}.log"
        with self.session_factory() as session:
            record = CommandExecutionRecord(
                run_id=run_id,
                mission_id=mission_id,
                task_key=task_key,
                kind=kind,
                command=command,
                cwd=str(cwd),
                status="running",
                log_path=str(log_path),
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._assemble_command(record)

    def _complete_command_execution(
        self,
        execution_id: str,
        exit_code: int,
        summary: str,
        *,
        log_path: Optional[str] = None,
    ) -> None:
        with self.session_factory() as session:
            record = session.get(CommandExecutionRecord, execution_id)
            if not record:
                return
            record.exit_code = exit_code
            record.summary = summary
            record.status = "completed" if exit_code == 0 else "failed"
            if log_path:
                record.log_path = log_path
            session.commit()

    def _create_artifact(self, mission_id: str, payload: ArtifactPayload) -> None:
        with self.session_factory() as session:
            session.add(
                ArtifactRecord(
                    mission_id=mission_id,
                    kind=payload.kind,
                    title=payload.title,
                    body=payload.body,
                    repo_scope=payload.repo_scope,
                    uri=payload.uri,
                    attributes=payload.metadata,
                )
            )
            session.commit()

    def _assemble_run(self, session, record: MissionRunRecord) -> MissionRunView:
        last_command_record = session.execute(
            select(CommandExecutionRecord)
            .where(CommandExecutionRecord.run_id == record.id)
            .order_by(CommandExecutionRecord.created_at.desc())
        ).scalars().first()
        last_command = self._assemble_command(last_command_record) if last_command_record else None
        return MissionRunView(
            id=record.id,
            mission_id=record.mission_id,
            status=record.status,
            current_task_key=record.current_task_key,
            branch_name=record.branch_name,
            worktree_path=record.worktree_path,
            merge_target=record.merge_target,
            deploy_targets=record.deploy_targets or [],
            last_heartbeat_at=record.last_heartbeat_at,
            last_error=record.last_error,
            started_at=record.started_at,
            completed_at=record.completed_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
            last_command=last_command,
        )

    def _assemble_command(self, record: CommandExecutionRecord) -> CommandExecutionView:
        return CommandExecutionView(
            id=record.id,
            run_id=record.run_id,
            mission_id=record.mission_id,
            task_key=record.task_key,
            kind=record.kind,
            command=record.command,
            cwd=record.cwd,
            status=record.status,
            exit_code=record.exit_code,
            summary=record.summary,
            log_path=record.log_path,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _check_runtime_budget(
        self,
        mission_id: str,
        run_id: str,
        *,
        task_key: Optional[str] = None,
    ) -> None:
        with self.session_factory() as session:
            mission = session.get(MissionRecord, mission_id)
            if not mission:
                return
            spec = MissionSpec.model_validate(mission.spec_payload or {})
            controls = spec.execution_controls.normalized(has_deploy_targets=bool(spec.deploy_targets))
            elapsed_hours = self._runtime_budget_elapsed_hours(session, mission_id)
            if not self._runtime_budget_reached(controls, elapsed_hours):
                return

        self._create_artifact(
            mission_id,
            ArtifactPayload(
                kind="runtime_budget_stop",
                title="Mission runtime budget reached",
                body=(
                    f"Mission stopped after reaching the configured runtime budget.\n"
                    f"Elapsed hours: {elapsed_hours:.2f}\n"
                    f"Limit hours: {controls.max_runtime_hours}\n"
                    f"Task at stop: {task_key or self._require_run(run_id).current_task_key or 'idle'}"
                ),
                metadata={
                    "task_key": task_key,
                    "elapsed_hours": round(elapsed_hours, 2),
                    "limit_hours": controls.max_runtime_hours,
                },
            ),
        )
        raise RuntimeBudgetExceeded(
            f"Mission runtime budget reached ({elapsed_hours:.2f}h / {controls.max_runtime_hours}h)."
        )

    def _runtime_budget_elapsed_hours(self, session, mission_id: str) -> float:
        runs = list(
            session.execute(
                select(MissionRunRecord)
                .where(MissionRunRecord.mission_id == mission_id)
                .order_by(MissionRunRecord.created_at.asc())
            ).scalars()
        )
        if not runs:
            return 0.0

        now = utcnow()
        total_seconds = 0.0
        for run in runs:
            started_at = self._coerce_utc(run.started_at or run.created_at) or now
            completed_at = self._coerce_utc(run.completed_at) or now
            if completed_at < started_at:
                completed_at = started_at
            total_seconds += (completed_at - started_at).total_seconds()
        return round(total_seconds / 3600, 2)

    @staticmethod
    def _runtime_budget_reached(controls: MissionExecutionControls, elapsed_hours: float) -> bool:
        if controls.max_runtime_hours is None:
            return False
        return elapsed_hours >= controls.max_runtime_hours

    def _fail_if_interrupted(self, run_id: str) -> None:
        run = self._require_run(run_id)
        if run.status == "interrupted":
            raise RunInterrupted("Run interrupted by user.")

    def _ensure_command_success(self, exit_code: int, task_key: str, summary: str) -> None:
        if exit_code != 0:
            raise MissionExecutionError(f"Task '{task_key}' failed.\n{summary}")

    def _status_for_task(self, task_key: str) -> str:
        if task_key == "verify":
            return "verifying"
        if task_key in {"release", "deploy"}:
            return "releasing"
        return "running"

    def _release_notes_body(self, path: Path) -> str:
        if not path.exists():
            return "Autopilot release."
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        clipped = " | ".join(line.strip() for line in lines[:24] if line.strip())
        return clipped[:900] or "Autopilot release."

    def _ensure_release_repo_ready(
        self,
        mission_id: str,
        run_id: str,
        task_key: str,
        repo_path: Path,
        merge_target: str,
    ) -> None:
        branch = self._run_shell_logged(
            mission_id,
            run_id,
            task_key,
            "git",
            "git rev-parse --abbrev-ref HEAD",
            cwd=repo_path,
        )
        self._ensure_command_success(branch.exit_code, task_key, branch.summary)
        current_branch = branch.summary.strip()
        if current_branch != merge_target:
            raise MissionExecutionError(
                f"Release must run from the original local repo on branch '{merge_target}', "
                f"but '{repo_path}' is on '{current_branch or 'unknown'}'."
            )

        status = self._run_shell_logged(
            mission_id,
            run_id,
            task_key,
            "git",
            "git status --short",
            cwd=repo_path,
        )
        self._ensure_command_success(status.exit_code, task_key, status.summary)
        if status.summary.strip():
            raise MissionExecutionError(
                "Release must run from the original local repo, but that checkout has pending local changes "
                "and would not build exactly the merged commit.\n"
                f"Repo: {repo_path}\n"
                f"{status.summary.strip()}"
            )

    def _normalize_release_prebuild_command(self, command: str, repo_path: Path) -> str:
        stripped = command.strip()
        if not stripped.startswith("npx expo ") or " prebuild" not in stripped:
            return command
        if stripped.startswith("npx --yes "):
            return command

        package_ref = self._resolve_expo_cli_package(repo_path)
        remainder = stripped[len("npx expo "):]
        return f"npx --yes {package_ref} {remainder}"

    def _resolve_expo_cli_package(self, repo_path: Path) -> str:
        lock_payload = self._read_json_file(repo_path / "package-lock.json")
        if lock_payload:
            packages = lock_payload.get("packages") or {}
            expo_package = packages.get("node_modules/expo") or {}
            version = str(expo_package.get("version") or "").strip()
            if version:
                return f"expo@{version}"

            dependencies = lock_payload.get("dependencies") or {}
            expo_dependency = dependencies.get("expo") or {}
            version = str(expo_dependency.get("version") or "").strip()
            if version:
                return f"expo@{version}"

        package_payload = self._read_json_file(repo_path / "package.json")
        if package_payload:
            dependency_maps = [
                package_payload.get("dependencies") or {},
                package_payload.get("devDependencies") or {},
            ]
            for dependency_map in dependency_maps:
                version = str(dependency_map.get("expo") or "").strip()
                if version:
                    return f"expo@{version}"

        return "expo"

    def _release_dependency_install_command(self, package_manager: str, repo_path: Path) -> Optional[str]:
        package_json = repo_path / "package.json"
        expo_module = repo_path / "node_modules" / "expo"
        if not package_json.exists() or expo_module.exists():
            return None

        manager = (package_manager or "npm").strip().lower()
        if manager == "npm":
            return "npm ci" if (repo_path / "package-lock.json").exists() else "npm install"
        if manager == "pnpm":
            return "pnpm install --frozen-lockfile" if (repo_path / "pnpm-lock.yaml").exists() else "pnpm install"
        if manager == "yarn":
            return "yarn install --frozen-lockfile" if (repo_path / "yarn.lock").exists() else "yarn install"
        return None

    @staticmethod
    def _read_json_file(path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _build_commit_diff_metadata(
        *,
        task_key: str,
        diff_stat: str,
        shortstat: str,
        name_status: str,
        commit_sha: str,
        commit_subject: str,
    ) -> dict:
        files_changed, insertions, deletions = RunnerService._parse_shortstat(shortstat)
        changed_files = RunnerService._parse_name_status(name_status)
        return {
            "task_key": task_key,
            "commit_sha": commit_sha or None,
            "commit_subject": commit_subject or None,
            "files_changed": files_changed or len(changed_files),
            "insertions": insertions,
            "deletions": deletions,
            "changed_files": changed_files,
            "diff_stat": diff_stat,
        }

    @staticmethod
    def _parse_shortstat(shortstat: str) -> tuple[int, int, int]:
        files_changed = 0
        insertions = 0
        deletions = 0
        for chunk in shortstat.splitlines():
            parts = [part.strip() for part in chunk.split(",") if part.strip()]
            for part in parts:
                if "file changed" in part or "files changed" in part:
                    files_changed = int(part.split()[0])
                elif "insertion" in part:
                    insertions = int(part.split()[0])
                elif "deletion" in part:
                    deletions = int(part.split()[0])
        return files_changed, insertions, deletions

    @staticmethod
    def _parse_name_status(name_status: str) -> list[dict[str, str]]:
        changed_files: list[dict[str, str]] = []
        for line in name_status.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            status = parts[0].strip() if parts else "committed"
            if len(parts) >= 3:
                path = f"{parts[1].strip()} -> {parts[2].strip()}"
            else:
                path = parts[-1].strip()
            if path:
                changed_files.append({"status": status or "committed", "path": path})
        return changed_files

    def _shell_quote(self, value: Path | str) -> str:
        text = str(value)
        escaped = text.replace("'", "'\"'\"'")
        return f"'{escaped}'"
