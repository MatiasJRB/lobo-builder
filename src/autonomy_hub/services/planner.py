from __future__ import annotations

import re
from dataclasses import dataclass

from autonomy_hub.adapters.filesystem import infer_surface
from autonomy_hub.domain.models import (
    ArtifactPayload,
    ConfigCatalog,
    ExecutionTaskSpec,
    MissionCreateRequest,
    MissionSpec,
    MissionType,
)


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


def slugify(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-") or "project"


class PlannerService:
    def __init__(self, catalog: ConfigCatalog):
        self.catalog = catalog

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
        template = self._select_template(mission, mission_type)
        spec = self._build_spec(mission, mission_type, template)
        tasks = self._build_tasks(mission, mission_type, template, spec)
        artifacts = self._build_artifacts(mission, mission_type, template, spec, tasks)
        return PlannerOutput(mission_type=mission_type, spec=spec, tasks=tasks, artifacts=artifacts)

    def _select_template(self, mission: MissionCreateRequest, mission_type: MissionType):
        if mission_type != "greenfield":
            return None

        haystack = f"{mission.brief} {mission.desired_outcome or ''}".lower()
        for template in self.catalog.templates.values():
            if any(keyword in haystack for keyword in template.when_keywords):
                return template

        return next(iter(self.catalog.templates.values()), None)

    def _build_spec(
        self,
        mission: MissionCreateRequest,
        mission_type: MissionType,
        template,
    ) -> MissionSpec:
        desired_outcome = mission.desired_outcome or "Leave the mission in a handoff-ready state."
        assumptions = [
            "Planner keeps global control and hands off only bounded repo/surface work.",
            "Mission starts in local interactive mode with isolated worktrees/checkouts.",
        ]
        risks = []

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
        )

    def _build_tasks(
        self,
        mission: MissionCreateRequest,
        mission_type: MissionType,
        template,
        spec: MissionSpec,
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

        implementation_tasks = self._build_implementation_tasks(mission, mission_type, template)
        tasks.extend(implementation_tasks)

        dependency_keys = [task.key for task in implementation_tasks] or ["architect-plan"]
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
        return tasks

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
            acceptance.append("Non-production deployment targets are eligible when explicitly linked.")
            expected.append("deployment")
        if mission.policy == "prod":
            acceptance.append("Production merge, deploy, and migrations are allowed only because the mission was created with prod policy.")
            expected.extend(["deployment", "release_note"])
        if mission.policy == "autopilot":
            merge_target = mission.merge_target or "main"
            acceptance.append(f"Every accepted cycle merges back into '{merge_target}'.")
            if mission.deploy_targets:
                acceptance.append(
                    "Deploy phase ships the declared delivery targets: " + ", ".join(mission.deploy_targets) + "."
                )
            else:
                acceptance.append("Deploy phase executes the mission's declared non-production/mobile delivery target.")
            expected = ["branch", "merge", "deployment", "release_note"]

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

    def _build_artifacts(
        self,
        mission: MissionCreateRequest,
        mission_type: MissionType,
        template,
        spec: MissionSpec,
        tasks: list[ExecutionTaskSpec],
    ) -> list[ArtifactPayload]:
        artifacts = [
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
        return (
            dominant_surface == "frontend"
            and len(repo_names) == 1
            and any(token in haystack for token in VISUAL_POLISH_HINTS)
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
