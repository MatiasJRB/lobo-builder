from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import Popen, STDOUT
from threading import Lock
import time
from typing import Callable, Optional


@dataclass
class CommandResult:
    command: str
    cwd: str
    exit_code: int
    log_path: str
    summary: str


class LocalCommandRunner:
    def __init__(self):
        self._active_processes: dict[str, Popen] = {}
        self._lock = Lock()

    def run(
        self,
        *,
        run_key: str,
        command: str,
        cwd: str,
        log_path: Path,
        env: Optional[dict[str, str]] = None,
        stop_when: Optional[Callable[[], bool]] = None,
        stop_grace_seconds: float = 3.0,
        stop_poll_interval_seconds: float = 0.5,
        treat_stopped_as_success: bool = False,
    ) -> CommandResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as handle:
            process = Popen(
                ["/bin/zsh", "-lc", command],
                cwd=cwd,
                stdout=handle,
                stderr=STDOUT,
                text=True,
                env=env,
            )
            with self._lock:
                self._active_processes[run_key] = process
            exit_code = self._wait_for_completion(
                process,
                stop_when=stop_when,
                stop_grace_seconds=stop_grace_seconds,
                stop_poll_interval_seconds=stop_poll_interval_seconds,
                treat_stopped_as_success=treat_stopped_as_success,
            )

        with self._lock:
            self._active_processes.pop(run_key, None)

        summary = self._tail(log_path)
        return CommandResult(
            command=command,
            cwd=cwd,
            exit_code=exit_code,
            log_path=str(log_path),
            summary=summary,
        )

    def interrupt(self, run_key: str) -> bool:
        with self._lock:
            process = self._active_processes.get(run_key)
        if not process:
            return False
        process.terminate()
        return True

    def _tail(self, log_path: Path, max_lines: int = 20) -> str:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not lines:
            return ""
        return "\n".join(lines[-max_lines:])

    def _wait_for_completion(
        self,
        process: Popen,
        *,
        stop_when: Optional[Callable[[], bool]],
        stop_grace_seconds: float,
        stop_poll_interval_seconds: float,
        treat_stopped_as_success: bool,
    ) -> int:
        if stop_when is None:
            return process.wait()

        completion_seen_at: Optional[float] = None
        while True:
            exit_code = process.poll()
            if exit_code is not None:
                return exit_code

            if stop_when():
                now = time.monotonic()
                completion_seen_at = completion_seen_at or now
                if now - completion_seen_at >= stop_grace_seconds:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except Exception:
                        process.kill()
                        process.wait(timeout=5)
                    return 0 if treat_stopped_as_success else (process.returncode or 0)
            else:
                completion_seen_at = None

            time.sleep(stop_poll_interval_seconds)
