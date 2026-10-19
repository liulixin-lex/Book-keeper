"""Settings loaded from ``BK_*`` environment variables."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BK_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://bk_app@localhost:5432/bookkeeper"
    migration_database_url: str | None = None
    data_dir: Path = Path("./data")
    web_dir: Path | None = None  # built frontend (web/dist); served at / when set
    public_url: str = "http://localhost:8000"
    environment: str = "development"

    session_idle_hours: int = 12
    session_absolute_days: int = 7
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    token_default_days: int = 90

    upload_max_bytes: int = 25 * 1024 * 1024
    idempotency_retention_days: int = 30

    mcp_enabled: bool = True
    mcp_write_enabled: bool = False
    # OAuth 2.1 sign-in for remote MCP clients (claude.ai, ChatGPT…); needs an https BK_PUBLIC_URL
    oauth_enabled: bool = False
    oauth_access_days: int = 30
    oauth_refresh_days: int = 180

    # AI 识别 import source: screenshots and PDFs → records through Claude. Off until a key is set
    # (BK_AI_API_KEY, or the SDK's own ANTHROPIC_API_KEY).
    ai_api_key: SecretStr | None = None
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"
    ai_max_files: int = 12  # per upload
    ai_daily_files: int = 200  # per book and day; 0 = no cap
    # Encrypts secrets stored in the database (AI provider keys). Without it, keys cannot be saved in 设置 → AI.
    master_key: SecretStr | None = None

    worker_poll_seconds: float = 2.0
    worker_heartbeat_seconds: float = 30.0

    log_level: str = "INFO"
    log_json: bool = True

    @property
    def ai_key(self) -> str | None:
        if self.ai_api_key is not None:
            return self.ai_api_key.get_secret_value() or None
        return os.environ.get("ANTHROPIC_API_KEY") or None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def production_problems(self) -> list[str]:
        """Settings that must not reach production (checked before serving or running the worker)."""
        if not self.is_production:
            return []
        problems = [
            f"{name} 仍是示例密码"
            for name, url in (
                ("BK_DATABASE_URL", self.database_url),
                ("BK_MIGRATION_DATABASE_URL", self.migration_database_url),
            )
            if url and "change-me" in url
        ]
        if self.master_key is not None and len(self.master_key.get_secret_value()) < 32:
            problems.append("BK_MASTER_KEY 太短：至少 32 个字符（如 openssl rand -hex 32）")
        if not self.public_url.startswith("https://"):
            problems.append("BK_PUBLIC_URL 必须使用 https://（会话 Cookie 与 OAuth 都需要）")
        return problems

    def ensure_deployable(self) -> None:
        if problems := self.production_problems():
            raise RuntimeError("生产配置不安全：" + "；".join(problems))

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    def effective_migration_url(self) -> str:
        return self.migration_database_url or self.database_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
