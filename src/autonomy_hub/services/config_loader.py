from __future__ import annotations

from pathlib import Path

import yaml

from autonomy_hub.domain.models import (
    AgentProfileConfig,
    ConfigCatalog,
    IntakeQuestion,
    MissionPolicyConfig,
    ProjectManifest,
    TemplateDefinition,
)


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_catalog(config_dir: Path) -> ConfigCatalog:
    agent_profiles_raw = _read_yaml(config_dir / "agent_profiles" / "catalog.yaml")
    policies_raw = _read_yaml(config_dir / "policies" / "catalog.yaml")
    intake_raw = _read_yaml(config_dir / "intake" / "greenfield-questionnaire.yaml")
    templates_raw = _read_yaml(config_dir / "templates" / "catalog.yaml")
    project_manifests_dir = config_dir / "projects"
    runner_prompts_dir = config_dir / "runner_prompts"

    agent_profiles = {
        item["slug"]: AgentProfileConfig.model_validate(item)
        for item in agent_profiles_raw.get("profiles", [])
    }
    policies = {
        item["slug"]: MissionPolicyConfig.model_validate(item)
        for item in policies_raw.get("policies", [])
    }
    intake_questions = [
        IntakeQuestion.model_validate(item) for item in intake_raw.get("questions", [])
    ]
    templates = {
        item["slug"]: TemplateDefinition.model_validate(item)
        for item in templates_raw.get("templates", [])
    }
    project_manifests = {}
    if project_manifests_dir.exists():
        for path in sorted(project_manifests_dir.glob("*.yaml")):
            manifest = ProjectManifest.model_validate(_read_yaml(path))
            project_manifests[manifest.repository] = manifest
    runner_prompts = {}
    if runner_prompts_dir.exists():
        for path in sorted(runner_prompts_dir.glob("*.md")):
            runner_prompts[path.stem] = path.read_text(encoding="utf-8").strip()

    return ConfigCatalog(
        agent_profiles=agent_profiles,
        policies=policies,
        intake_questions=intake_questions,
        templates=templates,
        project_manifests=project_manifests,
        runner_prompts=runner_prompts,
    )
