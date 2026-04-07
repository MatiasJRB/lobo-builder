from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


MissionType = Literal["fix", "feature", "refactor", "greenfield"]
MissionPolicySlug = Literal["safe", "delivery", "prod", "autopilot"]
TaskStatus = Literal["ready", "queued", "blocked", "running", "completed", "failed"]
MissionStatus = Literal["planned", "running", "verifying", "releasing", "completed", "failed", "interrupted"]
RunStatus = MissionStatus
CommandExecutionStatus = Literal["running", "completed", "failed", "interrupted"]


class MissionPolicyConfig(BaseModel):
    slug: MissionPolicySlug
    label: str
    description: str
    can_read: bool = True
    can_write: bool = True
    can_branch: bool = True
    can_worktree: bool = True
    can_commit: bool = True
    can_push: bool = True
    can_open_pr: bool = True
    can_merge: bool = False
    can_deploy: bool = False
    can_migrate: bool = False


class AgentProfileConfig(BaseModel):
    slug: str
    name: str
    role: str
    accepted_inputs: list[str] = Field(default_factory=list)
    required_outputs: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    handoff_rules: list[str] = Field(default_factory=list)


class TemplateRepositoryShape(BaseModel):
    name_pattern: str
    surface: str
    purpose: str


class TemplateDefinition(BaseModel):
    slug: str
    label: str
    description: str
    when_keywords: list[str] = Field(default_factory=list)
    stack: dict[str, str] = Field(default_factory=dict)
    default_repositories: list[TemplateRepositoryShape] = Field(default_factory=list)
    kickoff_artifacts: list[str] = Field(default_factory=list)


class AndroidDistributionConfig(BaseModel):
    apk_path: str = "android/app/build/outputs/apk/release/app-release.apk"
    release_notes_path: str = "RELEASE_NOTES.md"
    firebase_project: Optional[str] = None
    app_id: Optional[str] = None
    testers: Optional[str] = None
    prebuild_command: str = "npx expo prebuild --platform android --clean --no-install"
    assemble_command: str = "./gradlew assembleRelease --no-daemon"


class ProjectManifest(BaseModel):
    repository: str
    default_branch: Optional[str] = None
    package_manager: Optional[str] = None
    verify_commands: list[str] = Field(default_factory=list)
    release_targets: list[str] = Field(default_factory=list)
    android_distribution: Optional[AndroidDistributionConfig] = None


class IntakeQuestion(BaseModel):
    key: str
    prompt: str
    required: bool = True
    purpose: str


class MissionCreateRequest(BaseModel):
    brief: str
    desired_outcome: Optional[str] = None
    mission_type: Optional[MissionType] = None
    linked_repositories: list[str] = Field(default_factory=list)
    linked_products: list[str] = Field(default_factory=list)
    linked_documents: list[str] = Field(default_factory=list)
    policy: MissionPolicySlug = "safe"
    merge_target: Optional[str] = None
    deploy_targets: list[str] = Field(default_factory=list)


class MissionSpec(BaseModel):
    mission_type: MissionType
    summary: str
    desired_outcome: str
    merge_target: Optional[str] = None
    deploy_targets: list[str] = Field(default_factory=list)
    done_definition: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    repo_strategy: list[str] = Field(default_factory=list)
    template_slug: Optional[str] = None


class ExecutionTaskSpec(BaseModel):
    key: str
    title: str
    agent_profile_slug: str
    repo_scope: list[str] = Field(default_factory=list)
    surface: str
    status: TaskStatus = "queued"
    acceptance_criteria: list[str] = Field(default_factory=list)
    expected_artifacts: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class ArtifactPayload(BaseModel):
    kind: str
    title: str
    body: str
    repo_scope: list[str] = Field(default_factory=list)
    uri: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphNodeView(BaseModel):
    node_key: str
    kind: str
    name: str
    slug: str
    external_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeView(BaseModel):
    source_key: str
    relation: str
    target_key: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphSnapshot(BaseModel):
    counts: dict[str, int] = Field(default_factory=dict)
    nodes: list[GraphNodeView] = Field(default_factory=list)
    edges: list[GraphEdgeView] = Field(default_factory=list)


class WorktreeFileChangeView(BaseModel):
    status: str
    path: str


class WorktreeBatchView(BaseModel):
    task_key: Optional[str] = None
    commit_sha: Optional[str] = None
    commit_subject: Optional[str] = None
    files_count: int = 0
    insertions: int = 0
    deletions: int = 0
    changed_files: list[WorktreeFileChangeView] = Field(default_factory=list)
    diff_stat: Optional[str] = None


class WorktreeSnapshotView(BaseModel):
    branch_name: Optional[str] = None
    worktree_path: Optional[str] = None
    has_changes: bool = False
    changed_files: list[WorktreeFileChangeView] = Field(default_factory=list)
    diff_stat: Optional[str] = None
    head_summary: Optional[str] = None
    dirty_files_count: int = 0
    dirty_insertions: int = 0
    dirty_deletions: int = 0
    last_committed_batch: Optional[WorktreeBatchView] = None
    note: Optional[str] = None


class DashboardMissionItem(BaseModel):
    mission_id: str
    mission_type: MissionType
    status: MissionStatus
    policy: MissionPolicySlug
    current_owner: str
    next_step: str
    linked_repositories: list[str] = Field(default_factory=list)
    runtime_state: Optional[RunStatus] = None
    active_task_key: Optional[str] = None
    branch_name: Optional[str] = None
    worktree_path: Optional[str] = None
    changed_files_count: int = 0
    worktree_note: Optional[str] = None


class DashboardStatusItem(BaseModel):
    mission_id: str
    result: MissionStatus
    summary: str
    policy: MissionPolicyConfig
    permissions: dict[str, bool] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    merge_target: Optional[str] = None
    deploy_targets: list[str] = Field(default_factory=list)
    last_command: Optional[str] = None
    last_error: Optional[str] = None
    worktree_snapshot: Optional[WorktreeSnapshotView] = None


class CommandExecutionView(BaseModel):
    id: str
    run_id: str
    mission_id: str
    task_key: str
    kind: str
    command: str
    cwd: str
    status: CommandExecutionStatus
    exit_code: Optional[int] = None
    summary: Optional[str] = None
    log_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MissionRunView(BaseModel):
    id: str
    mission_id: str
    status: RunStatus
    current_task_key: Optional[str] = None
    branch_name: Optional[str] = None
    worktree_path: Optional[str] = None
    merge_target: Optional[str] = None
    deploy_targets: list[str] = Field(default_factory=list)
    last_heartbeat_at: Optional[datetime] = None
    last_error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    last_command: Optional[CommandExecutionView] = None


class DashboardSnapshot(BaseModel):
    queue: list[DashboardMissionItem] = Field(default_factory=list)
    status: list[DashboardStatusItem] = Field(default_factory=list)
    map: GraphSnapshot
    focused_mission_id: Optional[str] = None
    recent_commands: list[CommandExecutionView] = Field(default_factory=list)


class MissionView(BaseModel):
    id: str
    mission_type: MissionType
    brief: str
    desired_outcome: Optional[str] = None
    policy: MissionPolicyConfig
    status: MissionStatus
    linked_repositories: list[str] = Field(default_factory=list)
    linked_products: list[str] = Field(default_factory=list)
    linked_documents: list[str] = Field(default_factory=list)
    spec: MissionSpec
    artifacts: list[ArtifactPayload] = Field(default_factory=list)
    execution_tasks: list[ExecutionTaskSpec] = Field(default_factory=list)
    active_run: Optional[MissionRunView] = None
    worktree_snapshot: Optional[WorktreeSnapshotView] = None
    created_at: datetime
    updated_at: datetime


class ConfigCatalog(BaseModel):
    agent_profiles: dict[str, AgentProfileConfig]
    policies: dict[str, MissionPolicyConfig]
    intake_questions: list[IntakeQuestion]
    templates: dict[str, TemplateDefinition]
    project_manifests: dict[str, ProjectManifest] = Field(default_factory=dict)
    runner_prompts: dict[str, str] = Field(default_factory=dict)


class DiscoveryRequest(BaseModel):
    path: Optional[str] = None
    max_depth: int = 1


class MissionLogsView(BaseModel):
    mission_id: str
    runs: list[MissionRunView] = Field(default_factory=list)
    commands: list[CommandExecutionView] = Field(default_factory=list)
