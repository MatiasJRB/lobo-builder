from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class FirebaseAppDistributionAdapterSpec:
    label: str = "Firebase App Distribution"
    capabilities: tuple[str, ...] = (
        "android-app-distribution",
        "tester-groups",
        "release-notes",
    )
    environment_variables: tuple[str, ...] = ("FIREBASE_TOKEN", "GOOGLE_APPLICATION_CREDENTIALS")
    notes: str = "Mobile delivery target for Android builds that should reach testers without a full store release."

    def describe(self) -> dict[str, object]:
        return asdict(self)
