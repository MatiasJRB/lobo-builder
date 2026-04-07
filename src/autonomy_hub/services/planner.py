from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from autonomy_hub.adapters.filesystem import infer_surface
from autonomy_hub.config import Settings
from autonomy_hub.domain.models import (
    ArtifactPayload,
    ConfigCatalog,
    DecompositionProposal,
    ExecutionTaskSpec,
    MissionCreateRequest,
    MissionExecutionControls,
    MissionSpec,
    MissionType,
    PlanningContext,
    PlanningContextInput,
    RepoInstructionSummary,
    WorkUnit,
)
from autonomy_hub.services.project_context import discover_repo_instructions, resolve_repository_path


FIX_KEYWORDS = ("fix", "bug", "error", "incident", "regression", "hotfix", "broken")
REFACTOR_KEYWORDS = ("refactor", "cleanup", "rewrite", "reorganize", "modularize", "migrate")
GREENFIELD_KEYWORDS = (
    "greenfield",
    "desde cero",
    "nuevo repo",
    "new repo",
    "new project",
    "scaffold",
    "bootstrap",
    "sin repos",
    "project shell",
)

FRONTEND_HINTS = ("frontend", "web", "ui", "landing", "screen", "dashboard", "page")
BACKEND_HINTS = ("backend", "api", "endpoint", "service", "worker", "auth", "queue")
DATA_HINTS = ("database", "migration", "schema", "postgres", "railway", "infra", "deploy")
MOBILE_HINTS = ("mobile", "app", "expo", "react native", "native", "screen", "component")
VISUAL_POLISH_HINTS = (
    "visual",
    "ui",
    "ux",
    "polish",
    "consistency",
    "screen",
    "component",
    "design system",
    "tokens",
)


@dataclass
class PlannerOutput:
    mission_type: MissionType
    spec: MissionSpec
    tasks: list[ExecutionTaskSpec]
    artifacts: list[ArtifactPayload]
    planning_context: PlanningContext


def slugify(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-") or "project"


class PlannerService:
    def __init__(self, catalog: ConfigCatalog, settings: Optional[Settings] = None):
        self.catalog = catalog
        self.settings = settings

    def classify(self, mission: MissionCreateRequest) -> MissionType:
        if mission.mission_type:
            return mission.mission_type

        brief = mission.brief.lower()
        if not mission.linked_repositories or any(keyword in brief for keyword in GREENFIELD_KEYWORDS):
            return "greenfield"
        if any(keyword in brief for keyword in REFACTOR_KEYWORDS):
            return "refactor"
        if any(keyword in brief for keyword in FIX_KEYWORDS):
            return "fix"
        return "feature"

    def plan(self, mission: MissionCreateRequest) -> PlannerOutput:
        mission_type = self.classify(mission)
        repo_instruction_context = self._collect_repo_instruction_context(mission)
        template = self._select_template(mission, mission_type)
        planning_context = self._build_planning_context(
            mission,
            mission_type=mission_type,
            template=template,
            repo_instruction_context=repo_instruction_context,
        )
        spec = self._build_spec(mission, mission_type, template, repo_instruction_context, planning_context)
        tasks = self._build_tasks(
            mission,
            mission_type,
            template,
            spec,
            repo_instruction_context,
            planning_context,
        )
        artifacts = self._build_artifacts(
            mission,
            mission_type,
            template,
            spec,
            tasks,
            planning_context,
        )
        return PlannerOutput(
            mission_type=mission_type,
            spec=spec,
            tasks=tasks,
            artifacts=artifacts,
            planning_context=planning_context,
        )

    def _select_template(self, mission: MissionCreateRequest, mission_type: MissionType):
        if mission_type != "greenfield":
            return None

        haystack = f"{mission.brief} {mission.desired_outcome or ''}".lower()
        for template in self.catalog.templates.values():
            if any(keyword in haystack for keyword in template.when_keywords):
                return template

        return next(iter(self.catalog.templates.values()), None)

    def _build_planning_context(
        self,
        mission: MissionCreateRequest,
        *,
        mission_type: MissionType,
        template,
        repo_instruction_context: dict[str, RepoInstructionSummary],
    ) -> PlanningContext:
        repository_inputs = [
            self._inspect_repository_input(repository, repo_instruction_context.get(repository))
            for repository in mission.linked_repositories
        ]
        document_inputs = [self._inspect_linked_document(document_ref) for document_ref in mission.linked_documents]
        signals = self._collect_mission_signals(mission, repository_inputs, document_inputs)
        adaptive = self._should_use_adaptive_planning(mission, mission_type, template, signals, document_inputs)
        complexity = self._planning_complexity(mission, mission_type, signals, adaptive)
        notes = [
            "Planner inspects only structural signals from linked repositories and local documents.",
            "Fast path remains available for bounded single-repo work when extra expansion would add overhead.",
        ]
        if template:
            notes.append(f"Greenfield template candidate '{template.slug}' is part of planning context.")
        if adaptive:
            notes.append("Adaptive rolling-wave expansion will materialize implementation tasks after architect review.")

        repo_count = len([item for item in repository_inputs if item.reference])
        doc_count = len([item for item in document_inputs if item.reference])
        summary = (
            f"Planning context sees {repo_count} linked repos, {doc_count} linked documents, "
            f"and {len(signals)} structural mission signals."
        )
        return PlanningContext(
            planning_mode="adaptive" if adaptive else "fast-path",
            complexity=complexity,
            summary=summary,
            mission_signals=signals,
            repositories=repository_inputs,
            linked_documents=document_inputs,
            notes=notes,
        )

    def _inspect_repository_input(
        self,
        repository: str,
        repo_instructions: RepoInstructionSummary | None,
    ) -> PlanningContextInput:
        metadata: dict[str, object] = {}
        detected_surfaces: list[str] = []
        summary = "Repository reference is available but could not be inspected locally."

        if not self.settings:
            return PlanningContextInput(
                reference=repository,
                kind="repository",
                inspectable=False,
                summary=summary,
            )

        try:
            repo_path = resolve_repository_path(self.settings, repository)
        except ValueError:
            return PlanningContextInput(
                reference=repository,
                kind="repository",
                inspectable=False,
                summary=summary,
            )

        top_level_entries = sorted(path.name for path in repo_path.iterdir())[:12]
        manifest_files = [
            name
            for name in ["package.json", "pyproject.toml", "context/project.json", "astro.config.mjs", "firebase.json"]
            if (repo_path / name).exists()
        ]
        if (repo_path / "app").exists() or (repo_path / "src").exists():
            detected_surfaces.append("frontend")
        if (repo_path / "api").exists() or (repo_path / "backend").exists() or (repo_path / "server").exists():
            detected_surfaces.append("backend")
        if (repo_path / "migrations").exists() or (repo_path / "db").exists():
            detected_surfaces.append("data-infra")
        inferred_surface = infer_surface(repository)
        if not detected_surfaces and inferred_surface not in detected_surfaces:
            detected_surfaces.append(inferred_surface)

        summary = (
            f"Repository '{repository}' exposes {', '.join(top_level_entries[:6]) or 'no visible roots'} "
            f"and manifest hints {', '.join(manifest_files) or 'none'}."
        )
        if repo_instructions and repo_instructions.summary:
            summary += f" Repo guidance: {repo_instructions.summary}"

        metadata.update(
            {
                "path": str(repo_path),
                "top_level_entries": top_level_entries,
                "manifest_files": manifest_files,
                "has_context_project": (repo_path / "context" / "project.json").exists(),
                "has_repo_instructions": bool(
                    repo_instructions and (repo_instructions.agents_paths or repo_instructions.skill_paths)
                ),
            }
        )
        return PlanningContextInput(
            reference=repository,
            kind="repository",
            inspectable=True,
            summary=summary,
            detected_surfaces=detected_surfaces,
            metadata=metadata,
        )

    def _inspect_linked_document(self, document_ref: str) -> PlanningContextInput:
        candidate = self._resolve_local_path(document_ref)
        if not candidate:
            return PlanningContextInput(
                reference=document_ref,
                kind="string",
                inspectable=False,
                summary="Linked document is treated as a textual reference only.",
            )

        if candidate.is_file():
            return self._inspect_document_file(document_ref, candidate)
        if candidate.is_dir():
            return self._inspect_document_directory(document_ref, candidate)
        return PlanningContextInput(
            reference=document_ref,
            kind="string",
            inspectable=False,
            summary="Linked document reference exists locally but is not a regular file or directory.",
        )

    def _inspect_document_file(self, reference: str, path: Path) -> PlanningContextInput:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        excerpt = " ".join(lines[:5])[:280] if lines else "Empty file."
        detected_surfaces = self._surfaces_from_text(f"{path.name}\n{text[:1200]}")
        metadata = {
            "path": str(path),
            "suffix": path.suffix,
            "size_bytes": path.stat().st_size,
        }
        return PlanningContextInput(
            reference=reference,
            kind="file",
            inspectable=True,
            summary=f"Local file '{path.name}' preview: {excerpt}",
            detected_surfaces=detected_surfaces,
            metadata=metadata,
        )

    def _inspect_document_directory(self, reference: str, path: Path) -> PlanningContextInput:
        children = sorted(child.name for child in path.iterdir())[:16]
        detected_surfaces = self._surfaces_from_text(" ".join(children + [path.name]))
        metadata = {
            "path": str(path),
            "children": children,
        }
        return PlanningContextInput(
            reference=reference,
            kind="directory",
            inspectable=True,
            summary=(
                f"Local directory '{path.name}' contains {', '.join(children[:8]) or 'no visible children'}."
            ),
            detected_surfaces=detected_surfaces,
            metadata=metadata,
        )

    def _resolve_local_path(self, value: str) -> Path | None:
        if not self.settings:
            return None
        candidate = Path(value).expanduser()
        if candidate.is_absolute() and candidate.exists():
            return candidate.resolve()
        workspace_candidate = (self.settings.workspace_root / value).resolve()
        if workspace_candidate.exists():
            return workspace_candidate
        return None

    def _collect_mission_signals(
        self,
        mission: MissionCreateRequest,
        repositories: list[PlanningContextInput],
        documents: list[PlanningContextInput],
    ) -> list[str]:
        signals: list[str] = []
        haystack = " ".join(
            [
                mission.brief,
                mission.desired_outcome or "",
                *[item.summary for item in documents if item.inspectable],
            ]
        ).lower()
        for label, hints in (
            ("frontend", FRONTEND_HINTS + MOBILE_HINTS),
            ("backend", BACKEND_HINTS),
            ("data-infra", DATA_HINTS),
        ):
            if any(token in haystack for token in hints):
                signals.append(label)
        if len(mission.linked_repositories) > 1:
            signals.append("multi-repo")
        if any(item.inspectable for item in documents):
            signals.append("inspectable-linked-documents")
        if any("frontend" in item.detected_surfaces for item in repositories) and any(
            "backend" in item.detected_surfaces or "data-infra" in item.detected_surfaces
            for item in repositories
        ):
            signals.append("mixed-surfaces")
        return list(dict.fromkeys(signals))

    def _should_use_adaptive_planning(
        self,
        mission: MissionCreateRequest,
        mission_type: MissionType,
        template,
        signals: list[str],
        documents: list[PlanningContextInput],
    ) -> bool:
        repo_names = list(mission.linked_repositories)
        if mission_type == "greenfield" and template:
            repo_names = [
                repo_shape.name_pattern.format(project_slug="project")
                for repo_shape in template.default_repositories
            ]
        if self._is_visual_polish_mission(mission, self._dominant_surface_from_brief(mission.brief), repo_names):
            return False
        if mission_type == "greenfield":
            return True
        if len(mission.linked_repositories) > 1:
            return True
        if any(item.inspectable for item in documents):
            return True
        if "mixed-surfaces" in signals:
            return True
        return False

    def _planning_complexity(
        self,
        mission: MissionCreateRequest,
        mission_type: MissionType,
        signals: list[str],
        adaptive: bool,
    ) -> str:
        if not adaptive:
            return "simple"
        if mission_type == "greenfield" or len(mission.linked_repositories) > 1:
            return "complex"
        if "mixed-surfaces" in signals or len(signals) >= 3:
            return "complex"
        return "balanced"

    def _surfaces_from_text(self, text: str) -> list[str]:
        haystack = text.lower()
        detected: list[str] = []
        if any(token in haystack for token in FRONTEND_HINTS + MOBILE_HINTS):
            detected.append("frontend")
        if any(token in haystack for token in BACKEND_HINTS):
            detected.append("backend")
        if any(token in haystack for token in DATA_HINTS):
            detected.append("data-infra")
        return detected

    def _build_spec(
        self,
        mission: MissionCreateRequest,
        mission_type: MissionType,
        template,
        repo_instruction_context: dict[str, RepoInstructionSummary],
        planning_context: PlanningContext,
    ) -> MissionSpec:
        execution_controls = self._normalize_execution_controls(mission.execution_controls, mission.deploy_targets)
        desired_outcome = mission.desired_outcome or "Leave the mission in a handoff-ready state."
        assumptions = [
            "Planner keeps global control and hands off only bounded repo/surface work.",
            "Mission starts in local interactive mode with isolated worktrees/checkouts.",
        ]
        risks = []
        assumptions.append(
            f"Planning mode starts as '{planning_context.planning_mode}' with complexity '{planning_context.complexity}'."
        )
        if any(item.inspectable for item in planning_context.linked_documents):
            assumptions.append("Linked local documents were inspected structurally before task decomposition.")

        if len(mission.linked_repositories) > 1:
            risks.append("Cross-repo coordination can drift unless shared acceptance criteria remain explicit.")
        if mission.policy == "safe":
            risks.append("Release actions stop at branch/push/PR boundaries.")
        if mission.policy == "autopilot":
            risks.append("Autopilot closes the loop through merge and deploy, so verification quality must stay strict.")
        if mission_type == "greenfield":
            assumptions.append("Project Shell is created before implementation and becomes the anchor for the graph.")
            risks.append("Initial template choice can bias repo boundaries; verify before scaling the scaffold.")

        repo_strategy = [
            "Create Mission Spec and Execution Graph before any code edit.",
            "Assign explicit ownership per repo or surface for every execution task.",
            f"Apply Mission Policy '{mission.policy}' as the hard gate for push, PR, merge, deploy, and migrations.",
        ]
        if planning_context.planning_mode == "adaptive":
            repo_strategy.append(
                "Use rolling-wave planning: architect first, then materialize implementation tasks from the planning context."
            )

        if mission.linked_repositories:
            repo_strategy.append(
                "Use local worktrees/checkouts for each linked repository to keep execution isolated."
            )
        elif template:
            repo_strategy.append(
                f"Bootstrap repo map from template '{template.slug}' and keep it editable from versioned config."
            )
        if mission.merge_target:
            repo_strategy.append(f"Close successful execution cycles by integrating back into '{mission.merge_target}'.")
        if mission.deploy_targets:
            repo_strategy.append(
                "Route deploy work only through the declared mission targets: "
                + ", ".join(mission.deploy_targets)
                + "."
            )

        for repo_name, repo_instructions in repo_instruction_context.items():
            if repo_instructions.summary:
                assumptions.append(
                    f"Repository '{repo_name}' provides repo-local operational guidance. {repo_instructions.summary}"
                )
            elif repo_instructions.agents_paths or repo_instructions.skill_slugs:
                assumptions.append(
                    f"Repository '{repo_name}' has repo-local AGENTS/skills guidance that should shape implementation decisions."
                )

            if repo_instructions.agents_paths or repo_instructions.skill_slugs:
                paths = ", ".join(repo_instructions.agents_paths + repo_instructions.skill_paths[:4]) or "repo-local instruction files"
                repo_strategy.append(
                    f"For '{repo_name}', prefer repo-local instructions at {paths} over hub hints when execution choices conflict."
                )
            if repo_instructions.skill_slugs:
                repo_strategy.append(
                    f"Use repo-local skill conventions for '{repo_name}' when they narrow the intended approach: "
                    + ", ".join(repo_instructions.skill_slugs[:8])
                    + ("." if len(repo_instructions.skill_slugs) <= 8 else ", …")
                )
            for warning in repo_instructions.warnings:
                risks.append(f"Instruction discovery warning for '{repo_name}': {warning}")

        done_definition = [
            "Mission has a persisted spec artifact and a persisted execution graph.",
            "The dashboard shows the active owner, next step, produced artifacts, and graph relationships.",
            "Specialist tasks are laid out with acceptance criteria and expected artifacts.",
        ]

        if mission.policy == "delivery":
            done_definition.append("Non-production deploy path is prepared for the Release/Deploy profile.")
        if mission.policy == "prod":
            done_definition.append("Merge, production deploy, and migrations are explicitly policy-allowed.")
        if mission.policy == "autopilot":
            merge_target = mission.merge_target or "main"
            done_definition.append(f"Each accepted cycle merges back into '{merge_target}'.")
            if mission.deploy_targets:
                done_definition.append(
                    "Deploy phase executes the declared delivery targets: " + ", ".join(mission.deploy_targets) + "."
                )
        if mission_type == "greenfield" and template:
            done_definition.append(
                f"Greenfield output includes a project shell, template selection '{template.slug}', and starter repo map."
            )

        summary = mission.brief.strip().splitlines()[0][:240]

        return MissionSpec(
            mission_type=mission_type,
            summary=summary,
            desired_outcome=desired_outcome,
            merge_target=mission.merge_target,
            deploy_targets=mission.deploy_targets,
            done_definition=done_definition,
            assumptions=assumptions,
            risks=risks,
            repo_strategy=repo_strategy,
            template_slug=template.slug if template else None,
            execution_controls=execution_controls,
        )

    def _build_tasks(
        self,
        mission: MissionCreateRequest,
        mission_type: MissionType,
        template,
        spec: MissionSpec,
        repo_instruction_context: dict[str, RepoInstructionSummary],
        planning_context: PlanningContext,
    ) -> list[ExecutionTaskSpec]:
        tasks: list[ExecutionTaskSpec] = [
            ExecutionTaskSpec(
                key="context-map",
                title="Resolve repositories, products, documents, and environments in the graph",
                agent_profile_slug="context-mapper",
                repo_scope=mission.linked_repositories,
                surface="graph",
                status="completed",
                acceptance_criteria=[
                    "Known repos and documents are linked to graph nodes.",
                    "Environment relationships are explicit enough for later release decisions.",
                ],
                expected_artifacts=["context_snapshot"],
                notes="Bootstrapped automatically on mission creation.",
            ),
            ExecutionTaskSpec(
                key="product-spec",
                title="Draft the Mission Spec and definition of done",
                agent_profile_slug="product-spec",
                repo_scope=mission.linked_repositories,
                surface="spec",
                status="completed",
                acceptance_criteria=[
                    "Mission type, desired outcome, done definition, assumptions, and risks are explicit.",
                    "Greenfield missions capture questionnaire-derived product context.",
                ],
                expected_artifacts=["spec"],
                notes="Initial draft is created by the planner and can be refined before implementation.",
            ),
            ExecutionTaskSpec(
                key="architect-plan",
                title="Lock the technical approach, repo boundaries, and execution order",
                agent_profile_slug="architect",
                repo_scope=mission.linked_repositories,
                surface="architecture",
                status="ready",
                acceptance_criteria=[
                    "Repo and surface ownership are explicit.",
                    "Parallelizable work is separated from blocking work.",
                ],
                expected_artifacts=["decision_log"],
                depends_on=["context-map", "product-spec"],
            ),
        ]

        if mission_type == "greenfield":
            tasks.insert(
                0,
                ExecutionTaskSpec(
                    key="project-shell",
                    title="Create the Project Shell in the graph and seed the target repo map",
                    agent_profile_slug="planner",
                    repo_scope=[],
                    surface="graph",
                    status="completed",
                    acceptance_criteria=[
                        "A Project Shell exists as a first-class graph anchor.",
                        "Template-driven target repos are visible before scaffolding work begins.",
                    ],
                    expected_artifacts=["project_shell", "repo_map"],
                    notes="Planner bootstrap task completed on mission creation.",
                ),
            )

        adaptive = planning_context.planning_mode == "adaptive"
        implementation_tasks = [] if adaptive else self._build_implementation_tasks(mission, mission_type, template)
        if adaptive:
            tasks.append(
                ExecutionTaskSpec(
                    key="planner-expand-wave-1",
                    title="Materialize the first implementation wave from planning context and architecture constraints",
                    agent_profile_slug="planner",
                    repo_scope=mission.linked_repositories,
                    surface="planning",
                    status="blocked",
                    acceptance_criteria=[
                        "Implementation tasks are generated only after architecture constraints are known.",
                        "Verify depends on the materialized wave, not on a placeholder stage.",
                    ],
                    expected_artifacts=["decomposition_proposal", "execution_graph"],
                    depends_on=["architect-plan"],
                    notes=(
                        "Adaptive planning mode. This stage expands wave 1 using inspectable local inputs, "
                        "profile capabilities, and the architect decision log."
                    ),
                )
            )
        tasks.extend(implementation_tasks)

        dependency_keys = [task.key for task in implementation_tasks] or (
            ["planner-expand-wave-1"] if adaptive else ["architect-plan"]
        )
        tasks.append(
            ExecutionTaskSpec(
                key="verify",
                title="Validate changes, regressions, and policy boundaries",
                agent_profile_slug="verifier-reviewer",
                repo_scope=mission.linked_repositories,
                surface="verification",
                status="blocked",
                acceptance_criteria=[
                    "Tests and validation steps are captured per owned surface.",
                    "Risks and regressions are summarized before release actions.",
                ],
                expected_artifacts=["verification_report"],
                depends_on=dependency_keys,
            )
        )
        tasks.append(self._build_release_task(mission))
        if mission.deploy_targets:
            tasks.append(self._build_deploy_task(mission))
        self._apply_repo_instruction_notes(tasks, repo_instruction_context)
        return tasks

    def _collect_repo_instruction_context(
        self,
        mission: MissionCreateRequest,
    ) -> dict[str, RepoInstructionSummary]:
        if not self.settings:
            return {}

        summaries: dict[str, RepoInstructionSummary] = {}
        for repository in mission.linked_repositories:
            try:
                repo_path = resolve_repository_path(self.settings, repository)
            except ValueError:
                continue
            hub_manifest = self.catalog.project_manifests.get(repository)
            summary = discover_repo_instructions(
                repo_path,
                hub_manifest.instruction_hints if hub_manifest else None,
            )
            if summary.agents_paths or summary.skill_paths or summary.warnings:
                summaries[repository] = summary
        return summaries

    def _apply_repo_instruction_notes(
        self,
        tasks: list[ExecutionTaskSpec],
        repo_instruction_context: dict[str, RepoInstructionSummary],
    ) -> None:
        for task in tasks:
            if not task.repo_scope:
                continue
            note_chunks = [chunk for chunk in [task.notes] if chunk]
            for repository in task.repo_scope:
                summary = repo_instruction_context.get(repository)
                if not summary:
                    continue
                paths = summary.agents_paths + summary.skill_paths
                chunk_parts = [
                    f"Repo-local instructions for {repository}:",
                    f"paths={', '.join(paths) if paths else 'none'}",
                    f"skills={', '.join(summary.skill_slugs) if summary.skill_slugs else 'none'}",
                ]
                if summary.summary:
                    chunk_parts.append(f"summary={summary.summary}")
                if summary.warnings:
                    chunk_parts.append(f"warnings={'; '.join(summary.warnings)}")
                note_chunks.append(" | ".join(chunk_parts))
            task.notes = "\n\n".join(note_chunks) if note_chunks else task.notes

    def _build_implementation_tasks(self, mission: MissionCreateRequest, mission_type: MissionType, template):
        planned_tasks: list[ExecutionTaskSpec] = []
        repo_names = list(mission.linked_repositories)
        dominant_surface = self._dominant_surface_from_brief(mission.brief)

        if mission_type == "greenfield" and template:
            project_seed = mission.linked_products[0] if mission.linked_products else mission.brief
            project_slug = slugify(project_seed)[:36]
            repo_names = [
                repo_shape.name_pattern.format(project_slug=project_slug)
                for repo_shape in template.default_repositories
            ]

        if not repo_names:
            repo_names = self._repo_names_from_brief(mission.brief)

        if self._is_visual_polish_mission(mission, dominant_surface, repo_names):
            return self._build_visual_polish_tasks(repo_names)

        for repo_name in repo_names:
            surface = infer_surface(repo_name)
            if surface == "backend" and dominant_surface != "backend":
                surface = dominant_surface
            profile = {
                "frontend": "frontend-implementer",
                "backend": "backend-implementer",
                "data-infra": "data-infra-implementer",
            }.get(surface, "backend-implementer")
            planned_tasks.append(
                ExecutionTaskSpec(
                    key=f"implement-{slugify(repo_name)}",
                    title=f"Implement owned changes for {repo_name}",
                    agent_profile_slug=profile,
                    repo_scope=[repo_name],
                    surface=surface,
                    status="queued",
                    acceptance_criteria=[
                        "Work stays inside the owned repo or surface boundary.",
                        "Expected artifacts are produced for the verifier and release profiles.",
                    ],
                    expected_artifacts=["diff_summary", "branch"],
                    depends_on=["architect-plan"],
                )
            )

        if mission_type == "greenfield" and template:
            planned_tasks.append(
                ExecutionTaskSpec(
                    key="bootstrap-data-infra",
                    title="Stand up persistence and deploy scaffolding for the selected template",
                    agent_profile_slug="data-infra-implementer",
                    repo_scope=[task.repo_scope[0] for task in planned_tasks if task.repo_scope],
                    surface="data-infra",
                    status="queued",
                    acceptance_criteria=[
                        "Local DB/dev runtime is runnable.",
                        "Remote deploy targets are documented without forcing cloud-first execution.",
                    ],
                    expected_artifacts=["environment_plan", "deployment_plan"],
                    depends_on=["architect-plan"],
                )
            )

        return planned_tasks

    def build_decomposition_proposal(
        self,
        mission: MissionCreateRequest,
        *,
        mission_type: MissionType,
        spec: MissionSpec,
        planning_context: PlanningContext,
    ) -> DecompositionProposal:
        repo_names = list(mission.linked_repositories) or self._repo_names_from_brief(mission.brief)
        dominant_surface = self._dominant_surface_from_brief(mission.brief)
        if self._is_visual_polish_mission(mission, dominant_surface, repo_names):
            work_units = self._work_units_from_visual_polish(repo_names)
            return DecompositionProposal(
                summary="Visual polish mission stays on the explicit phased cut strategy.",
                rationale="The work is already scoped as a cohesive three-step UI hardening sequence.",
                work_units=work_units,
                conservative_mode=False,
            )

        signals = planning_context.mission_signals
        work_units: list[WorkUnit] = []

        if len(repo_names) > 1:
            data_repo_ids: list[str] = []
            for repo_name in repo_names:
                surface = infer_surface(repo_name)
                profile = self._profile_for_surface(surface)
                unit_id = slugify(repo_name)
                depends_on = list(data_repo_ids) if surface in {"frontend", "backend"} and data_repo_ids else []
                work_units.append(
                    self._work_unit(
                        unit_id=unit_id,
                        title=f"Implement bounded work for {repo_name}",
                        profile_slug=profile,
                        repo_scope=[repo_name],
                        surface=surface,
                        outcome=f"Ship the owned {surface} slice in {repo_name} without crossing repo boundaries.",
                        depends_on=depends_on,
                        rationale="Multi-repo missions split by repo boundary first to preserve ownership clarity.",
                    )
                )
                if surface == "data-infra":
                    data_repo_ids.append(unit_id)
        else:
            repo_name = repo_names[0]
            needs_frontend = "frontend" in signals or dominant_surface == "frontend"
            needs_backend = "backend" in signals or dominant_surface == "backend"
            needs_data = "data-infra" in signals

            if needs_data and (needs_backend or needs_frontend):
                work_units.append(
                    self._work_unit(
                        unit_id=f"{slugify(repo_name)}-data-foundation",
                        title=f"Prepare schema, persistence, or deploy foundation in {repo_name}",
                        profile_slug="data-infra-implementer",
                        repo_scope=[repo_name],
                        surface="data-infra",
                        outcome="Establish the data or infra slice that later work depends on.",
                        rationale="Data/auth/integration foundations are split out when they unlock later backend or UI work.",
                    )
                )

            foundation_ids = [unit.id for unit in work_units]
            if needs_backend:
                work_units.append(
                    self._work_unit(
                        unit_id=f"{slugify(repo_name)}-backend",
                        title=f"Implement the backend capability slice in {repo_name}",
                        profile_slug="backend-implementer",
                        repo_scope=[repo_name],
                        surface="backend",
                        outcome="Land the API/service/backend slice for the mission.",
                        depends_on=foundation_ids,
                        rationale="Backend work stays cohesive around a single vertical capability.",
                    )
                )
            if needs_frontend:
                ui_dependencies = [unit.id for unit in work_units if unit.primary_surface in {"backend", "data-infra"}]
                work_units.append(
                    self._work_unit(
                        unit_id=f"{slugify(repo_name)}-frontend",
                        title=f"Implement the frontend flow or screen family in {repo_name}",
                        profile_slug="frontend-implementer",
                        repo_scope=[repo_name],
                        surface="frontend",
                        outcome="Complete the user-facing slice once dependent backend or data changes are in place.",
                        depends_on=ui_dependencies,
                        rationale="Frontend work stays focused on one flow family and does not absorb API or schema churn.",
                    )
                )

            if not work_units:
                work_units.append(
                    self._work_unit(
                        unit_id=slugify(repo_name),
                        title=f"Implement owned changes for {repo_name}",
                        profile_slug=self._profile_for_surface(dominant_surface),
                        repo_scope=[repo_name],
                        surface=dominant_surface,
                        outcome="Finish the bounded mission slice in one cohesive task.",
                        rationale="The mission is small enough that further splitting would add overhead with little gain.",
                    )
                )

        if mission_type == "greenfield" and spec.template_slug:
            work_units.append(
                self._work_unit(
                    unit_id="bootstrap-data-infra",
                    title="Stand up persistence and deploy scaffolding for the selected template",
                    profile_slug="data-infra-implementer",
                    repo_scope=repo_names,
                    surface="data-infra",
                    outcome="Prepare runtime and deployment scaffolding without forcing cloud-first assumptions.",
                    rationale="Greenfield templates need runnable infra scaffolding even when feature work is still expanding.",
                )
            )

        conservative_mode = planning_context.complexity == "conservative"
        unresolved_questions = []
        if not any(item.inspectable for item in planning_context.linked_documents) and mission.linked_documents:
            unresolved_questions.append("Linked documents could not be inspected locally; keep decomposition conservative.")

        return DecompositionProposal(
            summary=f"Wave 1 expands into {len(work_units)} bounded work units.",
            rationale=(
                "The planner sized work units to stay within one owner profile and one primary repo/surface, "
                "splitting only when data/backend/frontend dependencies made sequencing explicit."
            ),
            work_units=work_units,
            conservative_mode=conservative_mode,
            unresolved_questions=unresolved_questions,
        )

    def implementation_tasks_from_proposal(
        self,
        proposal: DecompositionProposal,
        *,
        gate_dependency: str = "planner-expand-wave-1",
    ) -> list[ExecutionTaskSpec]:
        task_keys = {unit.id: f"implement-{unit.id}" for unit in proposal.work_units}
        tasks: list[ExecutionTaskSpec] = []
        for unit in proposal.work_units:
            dependencies = [gate_dependency]
            dependencies.extend(task_keys[dep] for dep in unit.depends_on if dep in task_keys)
            tasks.append(
                ExecutionTaskSpec(
                    key=task_keys[unit.id],
                    title=unit.title,
                    agent_profile_slug=unit.owner_profile_slug,
                    repo_scope=unit.repo_scope,
                    surface=unit.primary_surface,
                    status="queued",
                    acceptance_criteria=[
                        "Work stays inside the owned repo or surface boundary.",
                        unit.outcome,
                    ],
                    expected_artifacts=["diff_summary", "branch"],
                    depends_on=list(dict.fromkeys(dependencies)),
                    notes=(
                        f"Adaptive work unit rationale: {unit.rationale or 'No extra rationale provided.'} "
                        f"| size_hint={unit.size_hint} | planning_source={unit.planning_source}"
                    ),
                )
            )
        return tasks

    def planning_context_from_artifacts(self, artifacts: list[ArtifactPayload]) -> PlanningContext | None:
        for artifact in reversed(artifacts):
            if artifact.kind != "planning_context":
                continue
            payload = artifact.metadata.get("planning_context")
            if isinstance(payload, dict):
                return PlanningContext.model_validate(payload)
        return None

    def _work_units_from_visual_polish(self, repo_names: list[str]) -> list[WorkUnit]:
        repo_name = repo_names[0]
        return [
            self._work_unit(
                unit_id=f"{slugify(repo_name)}-foundation",
                title=f"Normalize shared UI foundation and legacy patterns in {repo_name}",
                profile_slug="frontend-implementer",
                repo_scope=[repo_name],
                surface="frontend",
                outcome="Stabilize the shared UI base before sweeping the visible surface.",
                rationale="Foundation changes create multiplicative leverage across later polish tasks.",
            ),
            self._work_unit(
                unit_id=f"{slugify(repo_name)}-surface-sweep",
                title=f"Sweep every user-facing screen and component family in {repo_name}",
                profile_slug="frontend-implementer",
                repo_scope=[repo_name],
                surface="frontend",
                outcome="Bring the visible product surface onto one visual system.",
                depends_on=[f"{slugify(repo_name)}-foundation"],
                rationale="The surface sweep depends on the shared base layer being stable first.",
            ),
            self._work_unit(
                unit_id=f"{slugify(repo_name)}-coherence-hardening",
                title=f"Harden end-to-end visual coherence, states, and release readiness in {repo_name}",
                profile_slug="frontend-implementer",
                repo_scope=[repo_name],
                surface="frontend",
                outcome="Tighten edge states and final release-facing polish.",
                depends_on=[f"{slugify(repo_name)}-surface-sweep"],
                rationale="The final pass consolidates consistency only after the broad sweep lands.",
            ),
        ]

    def _work_unit(
        self,
        *,
        unit_id: str,
        title: str,
        profile_slug: str,
        repo_scope: list[str],
        surface: str,
        outcome: str,
        depends_on: list[str] | None = None,
        rationale: str | None = None,
    ) -> WorkUnit:
        profile = self.catalog.agent_profiles[profile_slug]
        return WorkUnit(
            id=unit_id,
            title=title,
            owner_profile_slug=profile_slug,
            repo_scope=repo_scope,
            primary_surface=surface,
            outcome=outcome,
            depends_on=depends_on or [],
            size_hint=profile.preferred_task_size,
            planning_source="adaptive",
            rationale=rationale,
        )

    def _profile_for_surface(self, surface: str) -> str:
        return {
            "frontend": "frontend-implementer",
            "backend": "backend-implementer",
            "data-infra": "data-infra-implementer",
        }.get(surface, "backend-implementer")

    def _build_visual_polish_tasks(self, repo_names: list[str]) -> list[ExecutionTaskSpec]:
        repo_name = repo_names[0]
        return [
            ExecutionTaskSpec(
                key=f"implement-{slugify(repo_name)}-foundation",
                title=f"Normalize shared UI foundation and legacy patterns in {repo_name}",
                agent_profile_slug="frontend-implementer",
                repo_scope=[repo_name],
                surface="frontend",
                status="queued",
                acceptance_criteria=[
                    "Shared UI primitives use the current design tokens and system components.",
                    "Legacy buttons, badges, and obvious hardcoded visual values are reduced at the base layer first.",
                ],
                expected_artifacts=["diff_summary", "branch"],
                depends_on=["architect-plan"],
                notes="Cut 1 of 3. Start with components and tokens that fan out across many screens.",
            ),
            ExecutionTaskSpec(
                key=f"implement-{slugify(repo_name)}-surface-sweep",
                title=f"Sweep every user-facing screen and component family in {repo_name}",
                agent_profile_slug="frontend-implementer",
                repo_scope=[repo_name],
                surface="frontend",
                status="queued",
                acceptance_criteria=[
                    "All user-facing screens and reusable components are brought onto the same visual system.",
                    "No visible surface is treated as out-of-scope because of route priority or perceived importance.",
                ],
                expected_artifacts=["diff_summary", "branch"],
                depends_on=[f"implement-{slugify(repo_name)}-foundation"],
                notes="Cut 2 of 3. Sweep the full visible product surface once the shared base layer is stable.",
            ),
            ExecutionTaskSpec(
                key=f"implement-{slugify(repo_name)}-coherence-hardening",
                title=f"Harden end-to-end visual coherence, states, and release readiness in {repo_name}",
                agent_profile_slug="frontend-implementer",
                repo_scope=[repo_name],
                surface="frontend",
                status="queued",
                acceptance_criteria=[
                    "Loading, empty, error, confirmation, and transition states align with the same visual language.",
                    "The repo finishes as a coherent end-to-end product, not as a collection of locally polished screens.",
                ],
                expected_artifacts=["diff_summary", "branch"],
                depends_on=[f"implement-{slugify(repo_name)}-surface-sweep"],
                notes="Cut 3 of 3. Finish by tightening global coherence, edge states, and release-facing polish.",
            ),
        ]

    def _repo_names_from_brief(self, brief: str) -> list[str]:
        haystack = brief.lower()
        repo_names: list[str] = []
        if any(token in haystack for token in FRONTEND_HINTS):
            repo_names.append("frontend-surface")
        if any(token in haystack for token in BACKEND_HINTS):
            repo_names.append("backend-surface")
        if any(token in haystack for token in DATA_HINTS):
            repo_names.append("data-infra-surface")
        return repo_names or ["backend-surface"]

    def _dominant_surface_from_brief(self, brief: str) -> str:
        haystack = brief.lower()

        frontend_score = sum(token in haystack for token in FRONTEND_HINTS) + sum(
            token in haystack for token in MOBILE_HINTS
        )
        backend_score = sum(token in haystack for token in BACKEND_HINTS)
        data_score = sum(token in haystack for token in DATA_HINTS)

        if data_score > max(frontend_score, backend_score):
            return "data-infra"
        if frontend_score >= backend_score:
            return "frontend"
        return "backend"

    def _build_release_task(self, mission: MissionCreateRequest) -> ExecutionTaskSpec:
        acceptance = [
            "Release step only executes actions allowed by Mission Policy.",
            "Branch, PR, deploy, merge, and migration decisions are summarized as artifacts.",
        ]
        expected = ["branch", "pull_request"]

        if mission.policy == "delivery":
            acceptance.append("Non-production release handling is eligible when explicitly linked.")
        if mission.policy == "prod":
            acceptance.append("Production merge, deploy, and migrations are allowed only because the mission was created with prod policy.")
            expected.append("release_note")
        if mission.policy == "autopilot":
            merge_target = mission.merge_target or "main"
            acceptance.append(f"Every accepted cycle merges back into '{merge_target}'.")
            if mission.deploy_targets:
                acceptance.append("Deploy handoff stays explicit and feeds the dedicated deploy stage.")
            else:
                acceptance.append("Release closes the loop without creating a separate deploy stage.")
            expected = ["branch", "merge", "release_note"]

        return ExecutionTaskSpec(
            key="release",
            title="Prepare release actions according to policy gates",
            agent_profile_slug="release-deploy",
            repo_scope=mission.linked_repositories,
            surface="release",
            status="blocked",
            acceptance_criteria=acceptance,
            expected_artifacts=expected,
            depends_on=["verify"],
            notes=(
                f"Merge target: {mission.merge_target or 'none declared'} | Deploy targets: "
                + (", ".join(mission.deploy_targets) if mission.deploy_targets else "none declared")
            ),
        )

    def _build_deploy_task(self, mission: MissionCreateRequest) -> ExecutionTaskSpec:
        return ExecutionTaskSpec(
            key="deploy",
            title="Execute the declared deploy targets after release succeeds",
            agent_profile_slug="release-deploy",
            repo_scope=mission.linked_repositories,
            surface="deploy",
            status="blocked",
            acceptance_criteria=[
                "Deploy only runs for declared targets and only if Mission Policy allows it.",
                "Deploy happens after release finishes so distribution uses the intended integration point.",
            ],
            expected_artifacts=["deployment"],
            depends_on=["release"],
            notes="Deploy targets: " + (", ".join(mission.deploy_targets) if mission.deploy_targets else "none declared"),
        )

    def _build_artifacts(
        self,
        mission: MissionCreateRequest,
        mission_type: MissionType,
        template,
        spec: MissionSpec,
        tasks: list[ExecutionTaskSpec],
        planning_context: PlanningContext,
    ) -> list[ArtifactPayload]:
        artifacts = [
            ArtifactPayload(
                kind="planning_context",
                title="Planning Context",
                body=self._planning_context_body(planning_context),
                repo_scope=mission.linked_repositories,
                metadata={
                    "planning_mode": planning_context.planning_mode,
                    "complexity": planning_context.complexity,
                    "planning_context": planning_context.model_dump(mode="json"),
                },
            ),
            ArtifactPayload(
                kind="spec",
                title="Mission Spec",
                body=self._spec_body(spec),
                repo_scope=mission.linked_repositories,
                metadata={"mission_type": mission_type, "policy": mission.policy},
            ),
            ArtifactPayload(
                kind="execution_graph",
                title="Execution Graph",
                body=self._execution_graph_body(tasks),
                repo_scope=mission.linked_repositories,
                metadata={"task_count": len(tasks)},
            ),
        ]

        if self._is_visual_polish_mission(
            mission,
            self._dominant_surface_from_brief(mission.brief),
            mission.linked_repositories,
        ):
            artifacts.append(
                ArtifactPayload(
                    kind="decision_log",
                    title="Architectural Cut Strategy",
                    body=self._visual_polish_cut_strategy(mission),
                    repo_scope=mission.linked_repositories,
                    metadata={"strategy": "visual-polish-phased-cuts"},
                )
            )

        if mission_type == "greenfield":
            project_slug = slugify(mission.linked_products[0] if mission.linked_products else mission.brief)[:36]
            artifacts.append(
                ArtifactPayload(
                    kind="project_shell",
                    title="Project Shell",
                    body=(
                        f"Project shell '{project_slug}' created as the graph anchor for a new initiative.\n"
                        "Next steps: refine product/spec, confirm repo boundaries, then scaffold."
                    ),
                    metadata={"project_slug": project_slug},
                )
            )

        if template:
            artifacts.append(
                ArtifactPayload(
                    kind="template_selection",
                    title="Template Selection",
                    body=(
                        f"Selected template: {template.slug}\n"
                        f"Label: {template.label}\n"
                        f"Description: {template.description}"
                    ),
                    metadata={"stack": template.stack},
                )
            )

        return artifacts

    def _spec_body(self, spec: MissionSpec) -> str:
        sections = [
            f"Mission Type: {spec.mission_type}",
            f"Summary: {spec.summary}",
            f"Desired Outcome: {spec.desired_outcome}",
            f"Merge Target: {spec.merge_target or 'not declared'}",
            "Deploy Targets:",
            *([f"- {item}" for item in spec.deploy_targets] or ["- none declared"]),
            "Definition of Done:",
            *[f"- {item}" for item in spec.done_definition],
            "Assumptions:",
            *[f"- {item}" for item in spec.assumptions],
            "Risks:",
            *[f"- {item}" for item in spec.risks],
            "Repo Strategy:",
            *[f"- {item}" for item in spec.repo_strategy],
            "Execution Controls:",
            f"- verify_enabled: {spec.execution_controls.verify_enabled}",
            f"- release_enabled: {spec.execution_controls.release_enabled}",
            f"- deploy_enabled: {spec.execution_controls.deploy_enabled}",
            f"- max_runtime_hours: {spec.execution_controls.max_runtime_hours if spec.execution_controls.max_runtime_hours is not None else 'none'}",
        ]
        if spec.template_slug:
            sections.append(f"Template: {spec.template_slug}")
        return "\n".join(sections)

    def _execution_graph_body(self, tasks: list[ExecutionTaskSpec]) -> str:
        lines = ["Execution tasks:"]
        for task in tasks:
            owner = self.catalog.agent_profiles[task.agent_profile_slug].name
            repo_scope = ", ".join(task.repo_scope) if task.repo_scope else "graph-level"
            lines.append(
                f"- [{task.status}] {task.key}: {task.title} | owner={owner} | scope={repo_scope}"
            )
        return "\n".join(lines)

    def _planning_context_body(self, planning_context: PlanningContext) -> str:
        lines = [
            f"Planning Mode: {planning_context.planning_mode}",
            f"Complexity: {planning_context.complexity}",
            f"Summary: {planning_context.summary}",
            "Mission Signals:",
            *([f"- {signal}" for signal in planning_context.mission_signals] or ["- none detected"]),
            "Repositories:",
        ]
        if planning_context.repositories:
            for repository in planning_context.repositories:
                lines.append(
                    f"- {repository.reference} | inspectable={repository.inspectable} | "
                    f"surfaces={', '.join(repository.detected_surfaces) or 'unknown'} | {repository.summary}"
                )
        else:
            lines.append("- none linked")
        lines.append("Linked Documents:")
        if planning_context.linked_documents:
            for document in planning_context.linked_documents:
                lines.append(
                    f"- {document.reference} | kind={document.kind} | inspectable={document.inspectable} | {document.summary}"
                )
        else:
            lines.append("- none linked")
        lines.append("Notes:")
        lines.extend(f"- {note}" for note in planning_context.notes)
        return "\n".join(lines)

    def decomposition_proposal_body(self, proposal: DecompositionProposal) -> str:
        lines = [
            f"Summary: {proposal.summary}",
            f"Rationale: {proposal.rationale}",
            f"Conservative Mode: {proposal.conservative_mode}",
            "Work Units:",
        ]
        for unit in proposal.work_units:
            lines.append(
                f"- {unit.id}: {unit.title} | owner={unit.owner_profile_slug} | "
                f"surface={unit.primary_surface} | repo_scope={', '.join(unit.repo_scope) or 'none'} | "
                f"depends_on={', '.join(unit.depends_on) or 'none'}"
            )
            lines.append(f"  outcome: {unit.outcome}")
            if unit.rationale:
                lines.append(f"  rationale: {unit.rationale}")
        lines.append("Unresolved Questions:")
        lines.extend(f"- {item}" for item in proposal.unresolved_questions or ["none"])
        return "\n".join(lines)

    def _is_visual_polish_mission(
        self,
        mission: MissionCreateRequest,
        dominant_surface: str,
        repo_names: list[str],
    ) -> bool:
        haystack = " ".join(
            [
                mission.brief,
                mission.desired_outcome or "",
                " ".join(mission.linked_documents),
            ]
        ).lower()
        explicit_polish_tokens = ("visual", "ux", "polish", "consistency", "design system", "tokens")
        return (
            dominant_surface == "frontend"
            and len(repo_names) == 1
            and any(token in haystack for token in explicit_polish_tokens)
            and not any(token in haystack for token in BACKEND_HINTS + DATA_HINTS)
        )

    def _visual_polish_cut_strategy(self, mission: MissionCreateRequest) -> str:
        repo_name = mission.linked_repositories[0] if mission.linked_repositories else "target repo"
        return "\n".join(
            [
                "Cut strategy for UI polish missions:",
                f"1. Foundation first in {repo_name}: shared components, tokens, and legacy interaction primitives.",
                "2. Full surface sweep second: bring every user-facing screen and component family onto the same system.",
                "3. Coherence hardening last: tighten empty/loading/error/transition states and release-facing polish.",
                "Why this cut works:",
                "- the cut is based on dependency and leverage, not on screen importance",
                "- shared primitives create multiplicative visual impact across the whole app",
                "- the final pass prevents local fixes from drifting back into a patchwork UI",
            ]
        )

    @staticmethod
    def _normalize_execution_controls(
        controls: MissionExecutionControls | None,
        deploy_targets: list[str],
    ) -> MissionExecutionControls:
        base = controls or MissionExecutionControls()
        return base.normalized(has_deploy_targets=bool(deploy_targets))
