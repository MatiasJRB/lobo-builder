from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class RailwayAdapterSpec:
    label: str = "Railway"
    capabilities: tuple[str, ...] = ("project-link", "service-inspect", "deploy-dev", "deploy-prod")
    environment_variables: tuple[str, ...] = ("RAILWAY_TOKEN",)
    notes: str = (
        "Default control-plane target for remote state. Local mode remains the default execution path."
    )

    def describe(self) -> dict[str, object]:
        return asdict(self)
