from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from autonomy_hub.adapters.command_runner import CommandResult, LocalCommandRunner
from autonomy_hub.config import Settings


@dataclass
class CodexExecResult:
    profile_slug: str
    command: str
    cwd: str
    exit_code: int
    log_path: str
    output_path: str
    final_output: str
    summary: str


class CodexExecAdapter:
    def __init__(self, settings: Settings, command_runner: LocalCommandRunner):
        self.settings = settings
        self.command_runner = command_runner

    def run(
        self,
        *,
        run_key: str,
        profile_slug: str,
        prompt: str,
        cwd: Path,
        log_dir: Path,
        add_dirs: Iterable[Path] = (),
    ) -> CodexExecResult:
        log_dir.mkdir(parents=True, exist_ok=True)
        output_path = log_dir / f"{profile_slug}-last-message.txt"
        jsonl_path = log_dir / f"{profile_slug}-events.jsonl"

        command_parts = [
            self.settings.codex_command,
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            "-o",
            self._quote(output_path),
            "-C",
            self._quote(cwd),
        ]
        for add_dir in add_dirs:
            command_parts.extend(["--add-dir", self._quote(add_dir)])
        command_parts.append(self._quote(prompt))

        command = " ".join(command_parts)
        result: CommandResult = self.command_runner.run(
            run_key=run_key,
            command=command,
            cwd=str(cwd),
            log_path=jsonl_path,
            stop_when=lambda: output_path.exists() and output_path.stat().st_size > 0,
            stop_grace_seconds=3.0,
            stop_poll_interval_seconds=0.5,
            treat_stopped_as_success=True,
        )
        final_output = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        summary = final_output or self._summarize_jsonl(jsonl_path) or result.summary
        return CodexExecResult(
            profile_slug=profile_slug,
            command=result.command,
            cwd=result.cwd,
            exit_code=result.exit_code,
            log_path=result.log_path,
            output_path=str(output_path),
            final_output=final_output,
            summary=summary,
        )

    def _summarize_jsonl(self, jsonl_path: Path) -> str:
        if not jsonl_path.exists():
            return ""
        messages: list[str] = []
        for line in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") == "message":
                text = payload.get("text")
                if text:
                    messages.append(text)
        return "\n".join(messages[-5:])

    def _quote(self, value: Path | str) -> str:
        text = str(value)
        escaped = text.replace("'", "'\"'\"'")
        return f"'{escaped}'"
