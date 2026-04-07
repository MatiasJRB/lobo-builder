from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from urllib.request import Request, urlopen

from autonomy_hub.domain.models import MissionRunView, MissionView


class DiscordWebhookAdapter:
    def __init__(self, webhook_url: Optional[str], *, timeout_seconds: float = 5.0):
        self.webhook_url = webhook_url.strip() if webhook_url else None
        self.timeout_seconds = timeout_seconds

    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def notify_run_finished(self, *, mission: MissionView, run: MissionRunView) -> None:
        if not self.webhook_url:
            return

        payload = {
            "content": self._build_message(mission=mission, run=run),
            "allowed_mentions": {"parse": []},
        }
        request = Request(
            self.webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "autonomy-hub/0.1",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            status_code = response.getcode()
            if status_code < 200 or status_code >= 300:
                raise RuntimeError(f"Discord webhook returned status {status_code}.")

    def _build_message(self, *, mission: MissionView, run: MissionRunView) -> str:
        lines = [
            f"Lobo Builder flow {run.status.upper()}",
            f"Mission: {self._clip_inline(mission.brief, 180)}",
            f"Mission ID: {mission.id}",
            f"Policy: {mission.policy.slug}",
            f"Repositories: {', '.join(mission.linked_repositories) or '(none)'}",
        ]
        if run.branch_name:
            lines.append(f"Branch: {run.branch_name}")
        if run.merge_target:
            lines.append(f"Merge target: {run.merge_target}")
        if run.deploy_targets:
            lines.append(f"Deploy targets: {', '.join(run.deploy_targets)}")
        if run.completed_at:
            lines.append(f"Finished at: {self._format_dt(run.completed_at)}")
        if run.last_error:
            lines.append(f"Error: {self._clip_inline(run.last_error, 500)}")
        return self._clip_block("\n".join(lines), 1900)

    @staticmethod
    def _format_dt(value: datetime) -> str:
        return value.isoformat()

    @staticmethod
    def _clip_inline(value: str, limit: int) -> str:
        collapsed = " ".join(value.split())
        if len(collapsed) <= limit:
            return collapsed
        return f"{collapsed[: limit - 3]}..."

    @staticmethod
    def _clip_block(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return f"{value[: limit - 3]}..."
