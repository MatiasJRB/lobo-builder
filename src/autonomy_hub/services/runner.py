from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Optional

from sqlalchemy import select

from autonomy_hub.adapters.codex_exec import CodexExecAdapter
from autonomy_hub.adapters.command_runner import CommandResult, LocalCommandRunner
from autonomy_hub.adapters.git import GitWorktreePlan, build_worktree_plan, has_remote, primary_remote
from autonomy_hub.config import Settings
from autonomy_hub.db import ArtifactRecord, CommandExecutionRecord, ExecutionTaskRecord, MissionRecord, MissionRunRecord, utcnow
from autonomy_hub.domain.models import (
    ArtifactPayload,
    CommandExecutionView,
    ConfigCatalog,
    ExecutionTaskSpec,
    MissionCreateRequest,
    MissionLogsView,
    MissionRunView,
    MissionView,
)
from autonomy_hub.services.missions import MissionService
from autonomy_hub.services.project_context import ProjectContextResolver, ResolvedProjectContext


class MissionExecutionError(RuntimeError):
    pass


class RunInterrupted(MissionExecutionError):
    pass


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
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.catalog = catalog
        self.mission_service = mission_service
        self.project_context_resolver = project_context_resolver
        self.command_runner = command_runner or LocalCommandRunner()
        self.codex_adapter = codex_adapter or CodexExecAdapter(settings, self.command_runner)
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
                    run.status = "interrupted"
                    run.last_error = "Marked interrupted after stale heartbeat on startup."
                    mission = session.get(MissionRecord, run.mission_id)
                    if mission:
                        mission.status = "interrupted"
                        touched_missions.add(mission.id)
            if touched_missions:
                session.commit()

    def start_run(self, mission_id: str, *, resume: bool = False) -> MissionRunView:
        with self._lock:
            existing_thread = self._threads.get(mission_id)
            if existing_thread and existing_thread.is_alive():
                return self._latest_run(mission_id)

        with self.session_factory() as session:
            mission = session.get(MissionRecord, mission_id)
            if not mission:
                raise KeyError(mission_id)

            latest_run = session.execute(
                select(MissionRunRecord)
                .where(MissionRunRecord.mission_id == mission_id)
                .order_by(MissionRunRecord.created_at.desc())
            ).scalars().first()

            if resume and latest_run:
                run = latest_run
                run.status = "running"
                run.last_error = None
                if not run.started_at:
                    run.started_at = utcnow()
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
        with self.session_factory() as session:
            record = session.get(MissionRunRecord, run.id)
            mission = session.get(MissionRecord, mission_id)
            if record and record.current_task_key:
                self._transition_current_task(
                    session,
                    mission_id=mission_id,
                    task_key=record.current_task_key,
                    next_status="ready",
                )
            if record:
                record.status = "interrupted"
                record.current_task_key = None
                record.last_error = "Interrupted by user request."
                record.last_heartbeat_at = utcnow()
            if mission:
                mission.status = "interrupted"
            session.commit()
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
            self._ensure_worktree(run_id, mission, project)

            while True:
                self._touch_run(run_id)
                self._fail_if_interrupted(run_id)
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
        self._set_task_status(mission_id, task.key, "running")
        self._set_run_state(run_id, current_task_key=task.key, status=self._status_for_task(task.key))

        if task.key == "architect-plan":
            self._run_architect(mission, task, project, run_id)
        elif task.key.startswith("implement-"):
            self._run_implementer(mission, task, project, run_id)
        elif task.key == "verify":
            self._run_verify(mission, task, project, run_id)
        elif task.key == "release":
            self._run_release(mission, task, project, run_id)
        else:
            raise MissionExecutionError(f"Runner does not know how to execute task '{task.key}'.")

        self._set_task_status(mission_id, task.key, "completed")

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
        self._create_artifact(
            mission.id,
            ArtifactPayload(
                kind="diff_summary",
                title=f"Diff Summary · {task.key}",
                body=diff_summary.summary,
                repo_scope=[project.repository],
                metadata={"task_key": task.key},
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
        mission_worktree = Path(run.worktree_path)
        merge_target = run.merge_target or project.default_branch
        merge_worktree = self.settings.runs_dir / mission.id / "merge-target"
        merge_worktree.parent.mkdir(parents=True, exist_ok=True)

        if not merge_worktree.exists():
            create_commands = [
                f"git -C '{project.repo_path}' worktree add --force '{merge_worktree}' {merge_target}",
            ]
            for command in create_commands:
                result = self._run_shell_logged(
                    mission.id,
                    run_id,
                    task.key,
                    "git",
                    command,
                    cwd=project.repo_path,
                )
                self._ensure_command_success(result.exit_code, task.key, result.summary)

        remote = primary_remote(str(project.repo_path))
        if remote:
            fetch = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                f"git fetch {remote} --prune",
                cwd=merge_worktree,
            )
            self._ensure_command_success(fetch.exit_code, task.key, fetch.summary)
            sync_main = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                f"git merge --ff-only {remote}/{merge_target}",
                cwd=merge_worktree,
            )
            self._ensure_command_success(sync_main.exit_code, task.key, sync_main.summary)

        merge_commit = self._run_shell_logged(
            mission.id,
            run_id,
            task.key,
            "git",
            f"git merge --no-ff {run.branch_name} -m 'Autopilot merge for mission {mission.id}'",
            cwd=merge_worktree,
        )
        self._ensure_command_success(merge_commit.exit_code, task.key, merge_commit.summary)

        if remote and mission.policy.can_push:
            push = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "git",
                f"git push {remote} {merge_target}",
                cwd=merge_worktree,
            )
            self._ensure_command_success(push.exit_code, task.key, push.summary)

        distribution = project.android_distribution
        if "android-firebase-app-distribution" in project.release_targets:
            if not distribution or not distribution.app_id or not distribution.testers:
                raise MissionExecutionError("Android Firebase distribution is configured but appId/testers are missing.")

            prebuild = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "android-build",
                distribution.prebuild_command,
                cwd=merge_worktree,
            )
            self._ensure_command_success(prebuild.exit_code, task.key, prebuild.summary)

            assemble = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "android-build",
                distribution.assemble_command,
                cwd=merge_worktree / "android",
            )
            self._ensure_command_success(assemble.exit_code, task.key, assemble.summary)

            release_notes = self._release_notes_body(merge_worktree / distribution.release_notes_path)
            distribute = self._run_shell_logged(
                mission.id,
                run_id,
                task.key,
                "firebase",
                (
                    f"firebase appdistribution:distribute {self._shell_quote(merge_worktree / distribution.apk_path)} "
                    f"--app {self._shell_quote(distribution.app_id)} "
                    f"--testers {self._shell_quote(distribution.testers)} "
                    f"--release-notes {self._shell_quote(release_notes)}"
                    + (
                        f" --project {self._shell_quote(distribution.firebase_project)}"
                        if distribution.firebase_project
                        else ""
                    )
                ),
                cwd=merge_worktree,
            )
            self._ensure_command_success(distribute.exit_code, task.key, distribute.summary)

            self._create_artifact(
                mission.id,
                ArtifactPayload(
                    kind="deployment",
                    title="Android Firebase Distribution",
                    body=distribute.summary,
                    repo_scope=[project.repository],
                    metadata={
                        "task_key": task.key,
                        "target": "android-firebase-app-distribution",
                        "apk_path": str(merge_worktree / distribution.apk_path),
                    },
                ),
            )

        release_note_body = self._release_notes_body(merge_worktree / (distribution.release_notes_path if distribution else "RELEASE_NOTES.md"))
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
            "{{LINKED_DOCUMENTS}}": "\n".join(mission.linked_documents) or "(none)",
            "{{EXTRA_SECTIONS}}": "\n\n".join(extra_sections or []),
        }
        rendered = template
        for token, value in replacements.items():
            rendered = rendered.replace(token, value)
        return rendered.strip()

    def _promote_and_pick_next_task(self, mission_id: str) -> Optional[ExecutionTaskSpec]:
        with self.session_factory() as session:
            task_records = list(
                session.execute(
                    select(ExecutionTaskRecord)
                    .where(ExecutionTaskRecord.mission_id == mission_id)
                    .order_by(ExecutionTaskRecord.created_at.asc())
                ).scalars()
            )
            completed = {task.task_key for task in task_records if task.status == "completed"}
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
        with self.session_factory() as session:
            mission = session.get(MissionRecord, mission_id)
            run = session.get(MissionRunRecord, run_id)
            if mission:
                mission.status = "completed"
            if run:
                run.status = "completed"
                run.current_task_key = None
                run.completed_at = utcnow()
                run.last_heartbeat_at = utcnow()
            session.commit()

    def _mark_run_failed(self, mission_id: str, run_id: str, error: str) -> None:
        with self.session_factory() as session:
            mission = session.get(MissionRecord, mission_id)
            run = session.get(MissionRunRecord, run_id)
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
                run.status = "failed"
                run.current_task_key = None
                run.last_error = error
                run.completed_at = utcnow()
                run.last_heartbeat_at = utcnow()
            session.commit()

    def _mark_run_interrupted(self, mission_id: str, run_id: str, error: str) -> None:
        with self.session_factory() as session:
            mission = session.get(MissionRecord, mission_id)
            run = session.get(MissionRunRecord, run_id)
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
                run.status = "interrupted"
                run.current_task_key = None
                run.last_error = error
                run.completed_at = utcnow()
                run.last_heartbeat_at = utcnow()
            session.commit()

    def _set_task_status(self, mission_id: str, task_key: str, status: str) -> None:
        with self.session_factory() as session:
            self._transition_current_task(session, mission_id=mission_id, task_key=task_key, next_status=status)
            session.commit()

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
        execution = self._create_command_execution(
            mission_id,
            run_id,
            task_key,
            "codex",
            f"codex exec ({profile_slug})",
            cwd,
        )
        result = self.codex_adapter.run(
            run_key=run_id,
            profile_slug=profile_slug,
            prompt=prompt,
            cwd=cwd,
            log_dir=Path(execution.log_path).parent,
            add_dirs=add_dirs,
        )
        summary = result.summary or result.final_output
        self._complete_command_execution(execution.id, result.exit_code, summary, log_path=result.log_path)
        self._touch_run(run_id)
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
        if task_key == "release":
            return "releasing"
        return "running"

    def _release_notes_body(self, path: Path) -> str:
        if not path.exists():
            return "Autopilot release."
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        clipped = " | ".join(line.strip() for line in lines[:24] if line.strip())
        return clipped[:900] or "Autopilot release."

    def _shell_quote(self, value: Path | str) -> str:
        text = str(value)
        escaped = text.replace("'", "'\"'\"'")
        return f"'{escaped}'"
