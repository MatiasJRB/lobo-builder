from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = BASE_DIR / "var" / "autonomy-hub.db"


class Settings(BaseSettings):
    app_name: str = "autonomy-hub"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8042
    database_url: str = Field(default_factory=lambda: f"sqlite+pysqlite:///{DEFAULT_DB_PATH}")
    config_dir: Path = BASE_DIR / "config"
    workspace_root: Path = BASE_DIR.parent
    runs_dir: Path = BASE_DIR / "var" / "runs"
    auto_discover_local: bool = True
    discover_max_depth: int = 1
    codex_command: str = "codex"
    runner_heartbeat_timeout_seconds: int = 300
    discord_webhook_url: Optional[str] = None
    discord_webhook_timeout_seconds: float = 5.0

    model_config = SettingsConfigDict(
        env_prefix="AUTONOMY_",
        env_file=BASE_DIR / ".env",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
