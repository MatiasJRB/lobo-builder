from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from autonomy_hub.config import Settings
from autonomy_hub.domain.models import AndroidDistributionConfig, ConfigCatalog, MissionCreateRequest, ProjectManifest


@dataclass
class ResolvedProjectContext:
    repository: str
    repo_path: Path
    default_branch: str
    package_manager: str
    verify_commands: list[str]
    release_targets: list[str]
    android_distribution: Optional[AndroidDistributionConfig]


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

        return ResolvedProjectContext(
            repository=repository,
            repo_path=repo_path,
            default_branch=default_branch,
            package_manager=package_manager,
            verify_commands=verify_commands,
            release_targets=release_targets,
            android_distribution=android_distribution,
        )

    def _resolve_repo_path(self, repository: str) -> Path:
        candidate = Path(repository).expanduser()
        if candidate.is_absolute() and candidate.exists():
            return candidate.resolve()

        workspace_candidate = (self.settings.workspace_root / repository).resolve()
        if workspace_candidate.exists():
            return workspace_candidate

        direct_matches = list(self.settings.workspace_root.glob(f"**/{repository}"))
        for match in direct_matches:
            if (match / ".git").exists():
                return match.resolve()
        raise ValueError(f"Repository '{repository}' could not be resolved inside {self.settings.workspace_root}.")

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
