from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class GitHubAdapterSpec:
    label: str = "GitHub"
    capabilities: tuple[str, ...] = ("repository-read", "branch-push", "pull-request", "review-sync")
    environment_variables: tuple[str, ...] = ("GITHUB_TOKEN",)
    notes: str = "Use the GitHub app/connector for metadata and PR lifecycle; keep CLI as fallback."

    def describe(self) -> dict[str, object]:
        return asdict(self)
