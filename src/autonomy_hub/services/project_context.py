from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from autonomy_hub.config import Settings
from autonomy_hub.domain.models import (
    AndroidDistributionConfig,
    ConfigCatalog,
    MissionCreateRequest,
    ProjectInstructionHints,
    ProjectManifest,
    RepoInstructionSummary,
)


@dataclass
class ResolvedProjectContext:
    repository: str
    repo_path: Path
    default_branch: str
    package_manager: str
    verify_commands: list[str]
    release_targets: list[str]
    android_distribution: Optional[AndroidDistributionConfig]
    repo_instructions: RepoInstructionSummary


def discover_repo_instructions(
    repo_path: Path,
    instruction_hints: Optional[ProjectInstructionHints] = None,
) -> RepoInstructionSummary:
    repo_path = repo_path.resolve()
    warnings: list[str] = []
    agents_paths: list[str] = []
    skill_paths: list[str] = []
    skill_slugs: list[str] = []
    seen_paths: set[str] = set()

    def to_relative(path: Path) -> str:
        try:
            return path.resolve().relative_to(repo_path).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    def add_agents_path(path: Path) -> None:
        relative = to_relative(path)
        if relative not in seen_paths:
            agents_paths.append(relative)
            seen_paths.add(relative)

    def add_skill_path(path: Path) -> None:
        relative = to_relative(path)
        if relative not in seen_paths:
            skill_paths.append(relative)
            seen_paths.add(relative)

    def add_skill_slug(slug: str) -> None:
        normalized = slug.strip()
        if normalized and normalized not in skill_slugs:
            skill_slugs.append(normalized)

    def collect_skills(root: Path) -> None:
        if root.is_file() and root.name == "SKILL.md":
            add_skill_path(root)
            add_skill_slug(root.parent.name)
            return
        if root.is_dir() and (root / "SKILL.md").exists():
            add_skill_path(root / "SKILL.md")
            add_skill_slug(root.name)
        if root.is_dir():
            for skill_file in sorted(root.rglob("SKILL.md")):
                add_skill_path(skill_file)
                add_skill_slug(skill_file.parent.name)

    agents_md = repo_path / "AGENTS.md"
    agents_dir = repo_path / ".agents"
    root_skills = repo_path / "skills"
    if agents_md.exists():
        add_agents_path(agents_md)
    if agents_dir.exists():
        add_agents_path(agents_dir)
        collect_skills(agents_dir / "skills")
    if root_skills.exists():
        collect_skills(root_skills)

    for hint in (instruction_hints.paths if instruction_hints else []):
        hinted_path = (repo_path / hint).resolve()
        if not hinted_path.exists():
            warnings.append(f"Instruction hint '{hint}' was not found in the repository.")
            continue

        relative_hint = to_relative(hinted_path)
        if relative_hint in {"AGENTS.md", ".agents", "skills"}:
            warnings.append(f"Instruction hint '{hint}' duplicates a standard repo-local instruction path and was ignored.")
            continue

        if hinted_path.is_file() and hinted_path.name == "AGENTS.md":
            if agents_md.exists():
                warnings.append(f"Instruction hint '{hint}' was ignored because root AGENTS.md takes precedence.")
                continue
            add_agents_path(hinted_path)
            continue

        if hinted_path.is_dir():
            if hinted_path.name == ".agents":
                if agents_dir.exists():
                    warnings.append(f"Instruction hint '{hint}' was ignored because root .agents takes precedence.")
                    continue
                add_agents_path(hinted_path)
                collect_skills(hinted_path / "skills")
                continue
            collect_skills(hinted_path)
            if list(hinted_path.rglob("AGENTS.md")):
                for candidate in sorted(hinted_path.rglob("AGENTS.md")):
                    if agents_md.exists():
                        warnings.append(f"Instruction hint '{hint}' contains AGENTS.md files, but root AGENTS.md takes precedence.")
                        break
                    add_agents_path(candidate)
                continue

    summary_parts: list[str] = []
    agents_excerpt = _instruction_excerpt(repo_path, agents_paths)
    if agents_excerpt:
        summary_parts.append(f"AGENTS guidance: {agents_excerpt}")
    elif agents_paths:
        summary_parts.append("Repo-local AGENTS paths are present and should be treated as high-confidence instructions.")
    if skill_slugs:
        preview = ", ".join(skill_slugs[:8])
        suffix = "…" if len(skill_slugs) > 8 else ""
        summary_parts.append(f"Repo-local skills detected: {preview}{suffix}.")
    if not summary_parts and warnings:
        summary_parts.append("Repo-local instruction discovery completed with warnings and no usable instruction files.")

    return RepoInstructionSummary(
        agents_paths=agents_paths,
        skill_paths=skill_paths,
        skill_slugs=skill_slugs,
        summary=" ".join(summary_parts),
        warnings=warnings,
    )


def _instruction_excerpt(repo_path: Path, agents_paths: list[str]) -> str:
    for relative_path in agents_paths:
        candidate = (repo_path / relative_path).resolve()
        if candidate.is_file() and candidate.name == "AGENTS.md":
            lines = [
                line.strip()
                for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            if not lines:
                continue
            excerpt = " ".join(lines[:3])
            return excerpt[:280]
    return ""


class ProjectContextResolver:
    def __init__(self, settings: Settings, catalog: ConfigCatalog):
        self.settings = settings
        self.catalog = catalog

    def resolve(self, mission: MissionCreateRequest) -> ResolvedProjectContext:
        if not mission.linked_repositories:
            raise ValueError("Runner requires at least one linked repository.")

        repository = mission.linked_repositories[0]
        repo_path = self._resolve_repo_path(repository)
        repo_context = self._read_repo_context(repo_path)
        hub_manifest = self.catalog.project_manifests.get(repository)

        default_branch = (
            mission.merge_target
            or self._get_manifest_value(hub_manifest, "default_branch")
            or repo_context.get("default_branch")
            or "main"
        )
        verify_commands = (
            self._get_manifest_value(hub_manifest, "verify_commands")
            or repo_context.get("verify_commands")
            or []
        )
        release_targets = (
            mission.deploy_targets
            or self._get_manifest_value(hub_manifest, "release_targets")
            or repo_context.get("release_targets")
            or []
        )
        package_manager = (
            self._get_manifest_value(hub_manifest, "package_manager")
            or repo_context.get("package_manager")
            or "npm"
        )
        android_distribution = self._resolve_android_distribution(repo_path, hub_manifest)
        repo_instructions = discover_repo_instructions(
            repo_path,
            hub_manifest.instruction_hints if hub_manifest else None,
        )

        return ResolvedProjectContext(
            repository=repository,
            repo_path=repo_path,
            default_branch=default_branch,
            package_manager=package_manager,
            verify_commands=verify_commands,
            release_targets=release_targets,
            android_distribution=android_distribution,
            repo_instructions=repo_instructions,
        )

    def _resolve_repo_path(self, repository: str) -> Path:
        return resolve_repository_path(self.settings, repository)

    def _read_repo_context(self, repo_path: Path) -> dict[str, Any]:
        context_file = repo_path / "context" / "project.json"
        if not context_file.exists():
            return {}
        payload = json.loads(context_file.read_text(encoding="utf-8"))
        release_targets: list[str] = []
        frontend_provider = (
            payload.get("deploy", {})
            .get("frontend", {})
            .get("provider")
        )
        if frontend_provider == "firebase_app_distribution":
            release_targets.append("android-firebase-app-distribution")
        return {
            "default_branch": payload.get("defaultBranch"),
            "verify_commands": payload.get("verify", {}).get("commands", []),
            "release_targets": release_targets,
        }

    def _resolve_android_distribution(
        self,
        repo_path: Path,
        hub_manifest: Optional[ProjectManifest],
    ) -> Optional[AndroidDistributionConfig]:
        manifest_config = hub_manifest.android_distribution if hub_manifest else None
        firebase_json = repo_path / "firebase.json"
        app_id = None
        testers = None
        firebase_project = None
        if firebase_json.exists():
            payload = json.loads(firebase_json.read_text(encoding="utf-8"))
            distribution = payload.get("appdistribution", {})
            app_id = distribution.get("appId")
            testers = distribution.get("testers")
            firebase_project = payload.get("project") or repo_path.name

        if manifest_config:
            merged = manifest_config.model_copy()
            if app_id and not merged.app_id:
                merged.app_id = app_id
            if testers and not merged.testers:
                merged.testers = testers
            if firebase_project and not merged.firebase_project:
                merged.firebase_project = firebase_project
            return merged

        if not app_id and not testers and not firebase_json.exists():
            return None

        return AndroidDistributionConfig(
            app_id=app_id,
            testers=testers,
            firebase_project=firebase_project,
        )

    def _get_manifest_value(self, manifest: Optional[ProjectManifest], key: str):
        if not manifest:
            return None
        value = getattr(manifest, key)
        return value if value not in (None, [], "") else None


def resolve_repository_path(settings: Settings, repository: str) -> Path:
    candidate = Path(repository).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()

    workspace_candidate = (settings.workspace_root / repository).resolve()
    if workspace_candidate.exists():
        return workspace_candidate

    direct_matches = list(settings.workspace_root.glob(f"**/{repository}"))
    for match in direct_matches:
        if (match / ".git").exists():
            return match.resolve()
    raise ValueError(f"Repository '{repository}' could not be resolved inside {settings.workspace_root}.")
