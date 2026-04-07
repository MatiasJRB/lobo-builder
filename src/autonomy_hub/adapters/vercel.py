from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class VercelAdapterSpec:
    label: str = "Vercel"
    capabilities: tuple[str, ...] = ("preview-deploy", "production-deploy", "project-map")
    environment_variables: tuple[str, ...] = ("VERCEL_TOKEN",)
    notes: str = "Optional deploy target for frontend surfaces discovered in the context graph."

    def describe(self) -> dict[str, object]:
        return asdict(self)
