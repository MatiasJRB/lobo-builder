from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SURFACE_HINTS = {
    "api": "backend",
    "backend": "backend",
    "server": "backend",
    "web": "frontend",
    "frontend": "frontend",
    "landing": "frontend",
    "backoffice": "frontend",
    "app": "frontend",
    "infra": "data-infra",
    "data": "data-infra",
    "ops": "data-infra",
}


@dataclass
class LocalRepositoryDescriptor:
    name: str
    path: Path
    surface: str
    family_slug: str


def infer_surface(name: str) -> str:
    normalized = name.lower().replace("_", "-")
    for suffix, surface in SURFACE_HINTS.items():
        if normalized.endswith(f"-{suffix}") or normalized == suffix:
            return surface
    return "backend"


def infer_family_slug(name: str) -> str:
    normalized = name.lower().replace("_", "-")
    for suffix in SURFACE_HINTS:
        token = f"-{suffix}"
        if normalized.endswith(token):
            return normalized[: -len(token)] or normalized
    return normalized


def discover_git_repositories(root: Path, max_depth: int = 1) -> list[LocalRepositoryDescriptor]:
    discovered: list[LocalRepositoryDescriptor] = []
    root = root.resolve()

    for candidate in root.rglob(".git"):
        if candidate.name != ".git":
            continue
        repo_path = candidate.parent
        depth = len(repo_path.relative_to(root).parts)
        if depth > max_depth:
            continue

        name = repo_path.name
        discovered.append(
            LocalRepositoryDescriptor(
                name=name,
                path=repo_path,
                surface=infer_surface(name),
                family_slug=infer_family_slug(name),
            )
        )

    unique = {item.path: item for item in discovered}
    return sorted(unique.values(), key=lambda item: item.name.lower())
