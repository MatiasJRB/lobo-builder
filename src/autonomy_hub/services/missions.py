from __future__ import annotations

import re
import subprocess
from pathlib import Path

from sqlalchemy import select

from autonomy_hub.config import Settings
from autonomy_hub.db import ArtifactRecord, CommandExecutionRecord, ExecutionTaskRecord, MissionRecord, MissionRunRecord
from autonomy_hub.domain.models import (
    ArtifactPayload,
    CommandExecutionView,
    ConfigCatalog,
    DashboardMissionItem,
    DashboardSnapshot,
    DashboardStatusItem,
    ExecutionTaskSpec,
    GraphSnapshot,
    MissionLogsView,
    MissionCreateRequest,
    MissionRunView,
    MissionView,
    WorktreeBatchView,
    WorktreeFileChangeView,
    WorktreeSnapshotView,
)
from autonomy_hub.services.graph import GraphService
from autonomy_hub.services.planner import PlannerService


class MissionService:
    def __init__(
        self,
        settings: Settings,
        session_factory,
        catalog: ConfigCatalog,
        graph_service: GraphService,
        planner: PlannerService,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.catalog = catalog
        self.graph_service = graph_service
        self.planner = planner

    def create_mission(self, payload: MissionCreateRequest) -> MissionView:
        if payload.policy not in self.catalog.policies:
            raise ValueError(f"Unknown policy '{payload.policy}'")

        planned = self.planner.plan(payload)
        project_name = payload.linked_products[0] if payload.linked_products else payload.brief[:48]

        with self.session_factory() as session:
            mission = MissionRecord(
                mission_type=planned.mission_type,
                brief=payload.brief,
                desired_outcome=payload.desired_outcome,
                policy_slug=payload.policy,
                status="planned",
                linked_repositories=payload.linked_repositories,
                linked_products=payload.linked_products,
                linked_documents=payload.linked_documents,
                spec_payload=planned.spec.model_dump(),
            )
            session.add(mission)
            session.flush()

            for task in planned.tasks:
                session.add(
                    ExecutionTaskRecord(
                        mission_id=mission.id,
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

            for artifact in planned.artifacts:
                session.add(
                    ArtifactRecord(
                        mission_id=mission.id,
                        kind=artifact.kind,
                        title=artifact.title,
                        body=artifact.body,
                        repo_scope=artifact.repo_scope,
                        uri=artifact.uri,
                        attributes=artifact.metadata,
                    )
                )

            session.commit()
            mission_id = mission.id

        if planned.mission_type == "greenfield":
            self.graph_service.create_project_shell(mission_id, project_name, planned.spec.template_slug)
        self.graph_service.link_mission(
            mission_id=mission_id,
            brief=payload.brief,
            policy_slug=payload.policy,
            linked_products=payload.linked_products,
            linked_repositories=payload.linked_repositories,
            linked_documents=payload.linked_documents,
            artifacts=planned.artifacts,
        )
        return self.get_mission(mission_id)

    def list_missions(self) -> list[MissionView]:
        with self.session_factory() as session:
            mission_records = session.execute(
                select(MissionRecord).order_by(MissionRecord.created_at.desc())
            ).scalars()
            return [self._assemble_mission(session, record) for record in mission_records]

    def get_mission(self, mission_id: str) -> MissionView:
        with self.session_factory() as session:
            record = session.get(MissionRecord, mission_id)
            if not record:
                raise KeyError(mission_id)
            return self._assemble_mission(session, record)

    def dashboard_snapshot(self) -> DashboardSnapshot:
        missions = self.list_missions()
        queue: list[DashboardMissionItem] = []
        status: list[DashboardStatusItem] = []
        recent_commands: list[CommandExecutionView] = []
        focused_mission: MissionView | None = missions[0] if missions else None

        for mission in missions[:12]:
            active_run = mission.active_run
            worktree_snapshot = mission.worktree_snapshot
            next_task = next(
                (task for task in mission.execution_tasks if task.status == "running"),
                next(
                    (task for task in mission.execution_tasks if task.status == "ready"),
                    next((task for task in mission.execution_tasks if task.status == "queued"), None),
                ),
            )
            owner_name = (
                self.catalog.agent_profiles[next_task.agent_profile_slug].name
                if next_task
                else "Planner"
            )
            next_step = next_task.title if next_task else "Mission has no remaining planned tasks."

            queue.append(
                DashboardMissionItem(
                    mission_id=mission.id,
                    mission_type=mission.mission_type,
                    status=mission.status,
                    policy=mission.policy.slug,
                    current_owner=owner_name,
                    next_step=next_step,
                    linked_repositories=mission.linked_repositories,
                    runtime_state=active_run.status if active_run else None,
                    active_task_key=active_run.current_task_key if active_run else None,
                    branch_name=active_run.branch_name if active_run else None,
                    worktree_path=active_run.worktree_path if active_run else None,
                    changed_files_count=len(worktree_snapshot.changed_files) if worktree_snapshot else 0,
                    worktree_note=worktree_snapshot.note if worktree_snapshot else None,
                )
            )
            permissions = {
                key: value
                for key, value in mission.policy.model_dump().items()
                if key.startswith("can_")
            }
            status.append(
                DashboardStatusItem(
                    mission_id=mission.id,
                    result=mission.status,
                    summary=mission.spec.summary,
                    policy=mission.policy,
                    permissions=permissions,
                    artifacts=[artifact.title for artifact in mission.artifacts],
                    merge_target=mission.spec.merge_target,
                    deploy_targets=mission.spec.deploy_targets,
                    last_command=active_run.last_command.command if active_run and active_run.last_command else None,
                    last_error=active_run.last_error if active_run else None,
                    worktree_snapshot=worktree_snapshot,
                )
            )
            if active_run and active_run.last_command:
                recent_commands.append(active_run.last_command)

        return DashboardSnapshot(
            queue=queue,
            status=status,
            map=self._focused_graph_snapshot(focused_mission),
            focused_mission_id=focused_mission.id if focused_mission else None,
            recent_commands=recent_commands[:12],
        )

    def list_runs(self, mission_id: str) -> list[MissionRunView]:
        with self.session_factory() as session:
            records = session.execute(
                select(MissionRunRecord)
                .where(MissionRunRecord.mission_id == mission_id)
                .order_by(MissionRunRecord.created_at.desc())
            ).scalars()
            return [self._assemble_run(session, record) for record in records]

    def mission_logs(self, mission_id: str) -> MissionLogsView:
        with self.session_factory() as session:
            runs = self.list_runs(mission_id)
            records = session.execute(
                select(CommandExecutionRecord)
                .where(CommandExecutionRecord.mission_id == mission_id)
                .order_by(CommandExecutionRecord.created_at.desc())
            ).scalars()
            commands = [self._assemble_command(record) for record in records]
            return MissionLogsView(mission_id=mission_id, runs=runs, commands=commands)

    def _assemble_mission(self, session, record: MissionRecord) -> MissionView:
        task_records = session.execute(
            select(ExecutionTaskRecord)
            .where(ExecutionTaskRecord.mission_id == record.id)
            .order_by(ExecutionTaskRecord.created_at.asc())
        ).scalars()
        artifact_records = session.execute(
            select(ArtifactRecord)
            .where(ArtifactRecord.mission_id == record.id)
            .order_by(ArtifactRecord.created_at.asc())
        ).scalars()

        tasks = [
            ExecutionTaskSpec(
                key=task.task_key,
                title=task.title,
                agent_profile_slug=task.agent_profile_slug,
                repo_scope=task.repo_scope or [],
                surface=task.surface,
                status=task.status,
                acceptance_criteria=task.acceptance_criteria or [],
                expected_artifacts=task.expected_artifacts or [],
                depends_on=task.depends_on or [],
                notes=task.notes,
            )
            for task in task_records
        ]
        artifacts = [
            ArtifactPayload(
                kind=artifact.kind,
                title=artifact.title,
                body=artifact.body,
                repo_scope=artifact.repo_scope or [],
                uri=artifact.uri,
                metadata=artifact.attributes or {},
            )
            for artifact in artifact_records
        ]
        active_run_record = session.execute(
            select(MissionRunRecord)
            .where(MissionRunRecord.mission_id == record.id)
            .order_by(MissionRunRecord.created_at.desc())
        ).scalars().first()
        active_run = self._assemble_run(session, active_run_record) if active_run_record else None
        worktree_snapshot = self._worktree_snapshot(active_run, artifacts)

        return MissionView(
            id=record.id,
            mission_type=record.mission_type,
            brief=record.brief,
            desired_outcome=record.desired_outcome,
            policy=self.catalog.policies[record.policy_slug],
            status=record.status,
            linked_repositories=record.linked_repositories or [],
            linked_products=record.linked_products or [],
            linked_documents=record.linked_documents or [],
            spec=record.spec_payload,
            artifacts=artifacts,
            execution_tasks=tasks,
            active_run=active_run,
            worktree_snapshot=worktree_snapshot,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

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

    def _worktree_snapshot(
        self,
        active_run: MissionRunView | None,
        artifacts: list[ArtifactPayload],
    ) -> WorktreeSnapshotView | None:
        if not active_run or not active_run.worktree_path:
            return None

        worktree_path = Path(active_run.worktree_path)
        last_committed_batch = self._latest_committed_batch(artifacts)
        if not worktree_path.exists():
            return WorktreeSnapshotView(
                branch_name=active_run.branch_name,
                worktree_path=active_run.worktree_path,
                last_committed_batch=last_committed_batch,
                note="El worktree de esta misión todavía no existe o ya fue removido.",
            )

        branch_name = self._git_output(worktree_path, "branch --show-current") or active_run.branch_name
        status_output = self._git_output(worktree_path, "status --short")
        changed_files = self._parse_git_status(status_output)
        dirty_shortstats = [
            output
            for output in [
                self._git_output(worktree_path, "diff --shortstat"),
                self._git_output(worktree_path, "diff --cached --shortstat"),
            ]
            if output
        ]
        diff_chunks = [
            output
            for output in [
                self._git_output(worktree_path, "diff --stat"),
                self._git_output(worktree_path, "diff --cached --stat"),
            ]
            if output
        ]
        head_summary = self._git_output(worktree_path, "log --oneline -1")
        _, dirty_insertions, dirty_deletions = self._sum_shortstats(dirty_shortstats)
        if changed_files:
            note = "Hay cambios sin commit en este worktree."
        elif last_committed_batch:
            note = "El worktree esta limpio. El ultimo batch ya fue commiteado y el agente puede estar cerrando o diagnosticando el siguiente corte."
        else:
            note = "Todavia no hay cambios de archivos en este worktree. El agente sigue en diagnostico o seleccion de superficie."
        return WorktreeSnapshotView(
            branch_name=branch_name,
            worktree_path=str(worktree_path),
            has_changes=bool(changed_files),
            changed_files=changed_files,
            diff_stat="\n\n".join(diff_chunks) if diff_chunks else None,
            head_summary=head_summary,
            dirty_files_count=len(changed_files),
            dirty_insertions=dirty_insertions,
            dirty_deletions=dirty_deletions,
            last_committed_batch=last_committed_batch,
            note=note,
        )

    def _latest_committed_batch(self, artifacts: list[ArtifactPayload]) -> WorktreeBatchView | None:
        for artifact in reversed(artifacts):
            if artifact.kind != "diff_summary":
                continue
            batch = self._batch_from_artifact(artifact)
            if batch and batch.commit_sha:
                return batch
        return None

    def _batch_from_artifact(self, artifact: ArtifactPayload) -> WorktreeBatchView | None:
        metadata = artifact.metadata or {}
        if metadata.get("no_changes"):
            return None

        parsed = self._parse_legacy_diff_summary(artifact.body)
        changed_files = self._coerce_changed_files(metadata.get("changed_files")) or parsed.changed_files
        commit_sha = metadata.get("commit_sha") or parsed.commit_sha
        commit_subject = metadata.get("commit_subject") or parsed.commit_subject
        diff_stat = metadata.get("diff_stat") or artifact.body or parsed.diff_stat
        files_count = int(metadata.get("files_changed") or metadata.get("files_count") or parsed.files_count or len(changed_files))
        insertions = int(metadata.get("insertions") or parsed.insertions or 0)
        deletions = int(metadata.get("deletions") or parsed.deletions or 0)
        task_key = metadata.get("task_key") or parsed.task_key

        if not any([commit_sha, commit_subject, diff_stat, changed_files]):
            return None

        return WorktreeBatchView(
            task_key=task_key,
            commit_sha=commit_sha,
            commit_subject=commit_subject,
            files_count=files_count,
            insertions=insertions,
            deletions=deletions,
            changed_files=changed_files,
            diff_stat=diff_stat,
        )

    def _focused_graph_snapshot(self, mission: MissionView | None) -> GraphSnapshot:
        if not mission:
            return GraphSnapshot()

        full = self.graph_service.snapshot()
        mission_key = f"mission:{mission.id}"
        relevant_keys = {mission_key}

        for edge in full.edges:
            if edge.source_key == mission_key or edge.target_key == mission_key:
                relevant_keys.add(edge.source_key)
                relevant_keys.add(edge.target_key)

        expanded = True
        while expanded:
            expanded = False
            for edge in full.edges:
                if edge.source_key in relevant_keys or edge.target_key in relevant_keys:
                    if edge.source_key not in relevant_keys or edge.target_key not in relevant_keys:
                        relevant_keys.add(edge.source_key)
                        relevant_keys.add(edge.target_key)
                        expanded = True

        filtered_nodes = [
            node
            for node in full.nodes
            if node.node_key in relevant_keys and node.kind.lower() != "agentprofile"
        ]
        filtered_edges = [
            edge
            for edge in full.edges
            if edge.source_key in relevant_keys and edge.target_key in relevant_keys
        ]

        counts: dict[str, int] = {}
        for node in filtered_nodes:
            label = self._display_kind(node.kind)
            counts[label] = counts.get(label, 0) + 1

        return GraphSnapshot(
            counts=counts,
            nodes=filtered_nodes,
            edges=filtered_edges,
        )

    @staticmethod
    def _git_output(worktree_path: Path, args: str) -> str:
        result = subprocess.run(
            ["/bin/zsh", "-lc", f"git -C '{worktree_path}' {args}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    @staticmethod
    def _parse_git_status(status_output: str) -> list[WorktreeFileChangeView]:
        changes: list[WorktreeFileChangeView] = []
        for line in status_output.splitlines():
            if not line.strip():
                continue
            status = line[:2].strip() or "??"
            path = line[3:].strip()
            changes.append(WorktreeFileChangeView(status=status, path=path))
        return changes

    @staticmethod
    def _coerce_changed_files(raw_files) -> list[WorktreeFileChangeView]:
        if not isinstance(raw_files, list):
            return []

        changes: list[WorktreeFileChangeView] = []
        for entry in raw_files:
            if isinstance(entry, WorktreeFileChangeView):
                changes.append(entry)
                continue
            if not isinstance(entry, dict):
                continue
            path = str(entry.get("path") or "").strip()
            if not path:
                continue
            status = str(entry.get("status") or "committed").strip() or "committed"
            changes.append(WorktreeFileChangeView(status=status, path=path))
        return changes

    @staticmethod
    def _sum_shortstats(shortstats: list[str]) -> tuple[int, int, int]:
        files_changed = 0
        insertions = 0
        deletions = 0
        for stat in shortstats:
            files, added, removed = MissionService._parse_shortstat_line(stat)
            files_changed += files
            insertions += added
            deletions += removed
        return files_changed, insertions, deletions

    @staticmethod
    def _parse_shortstat_line(shortstat: str) -> tuple[int, int, int]:
        if not shortstat:
            return 0, 0, 0
        files_match = re.search(r"(\d+)\s+files?\schanged", shortstat)
        insertions_match = re.search(r"(\d+)\s+insertions?\(\+\)", shortstat)
        deletions_match = re.search(r"(\d+)\s+deletions?\(-\)", shortstat)
        return (
            int(files_match.group(1)) if files_match else 0,
            int(insertions_match.group(1)) if insertions_match else 0,
            int(deletions_match.group(1)) if deletions_match else 0,
        )

    @staticmethod
    def _parse_legacy_diff_summary(body: str) -> WorktreeBatchView:
        commit_match = re.search(r"^commit\s+([0-9a-f]{7,40})", body, flags=re.MULTILINE)
        subject = None
        for line in body.splitlines():
            if line.startswith("    ") and line.strip():
                subject = line.strip()
                break

        changed_files: list[WorktreeFileChangeView] = []
        for line in body.splitlines():
            match = re.match(r"^\s*(.+?)\s+\|\s+\d+", line)
            if not match:
                continue
            path = match.group(1).strip()
            if path:
                changed_files.append(WorktreeFileChangeView(status="committed", path=path))

        files_count, insertions, deletions = MissionService._parse_shortstat_line(body)
        return WorktreeBatchView(
            commit_sha=commit_match.group(1) if commit_match else None,
            commit_subject=subject,
            files_count=files_count or len(changed_files),
            insertions=insertions,
            deletions=deletions,
            changed_files=changed_files,
            diff_stat=body or None,
        )

    @staticmethod
    def _display_kind(kind: str) -> str:
        words = kind.replace("_", " ").split()
        return " ".join(word.capitalize() for word in words)
