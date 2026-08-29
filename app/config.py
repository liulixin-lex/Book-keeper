from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.enums import AIProtocol, ReasoningEffort


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Book keeper"
    app_env: str = "development"
    app_secret_key: str = "development-only-change-me"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./data/ledger.db"
    backup_dir: Path = Path("./backups")
    ai_upload_dir: Path = Path("./data/ai-inputs")
    timezone: str = "Asia/Shanghai"
    base_currency: str = "CNY"

    session_cookie_name: str = "ledger_session"
    csrf_cookie_name: str = "ledger_csrf"
    session_cookie_secure: bool = False
    session_ttl_hours: int = Field(default=24 * 7, ge=1, le=24 * 90)
    invitation_ttl_hours: int = Field(default=72, ge=1, le=24 * 30)

    sqlite_busy_timeout_ms: int = Field(default=10_000, ge=1_000, le=120_000)
    sqlite_min_version: str = "3.51.3"
    backup_interval_seconds: int = Field(default=86_400, ge=300)
    knowledge_worker_interval_seconds: int = Field(default=5, ge=1, le=300)

    ai_max_files_per_workflow: int = Field(default=10, ge=1, le=100)
    ai_max_file_size_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    ai_max_total_file_size_bytes: int = Field(default=100 * 1024 * 1024, ge=1024)
    ai_failed_file_ttl_hours: int = Field(default=24, ge=1, le=168)

    ai_default_base_url: str = "https://api.aiaimax.com/v1"
    ai_default_protocol: AIProtocol = AIProtocol.RESPONSES
    ai_default_model: str = ""
    ai_default_effort: ReasoningEffort = ReasoningEffort.MEDIUM
    openai_api_key: str | None = None
    embedding_api_key: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    def ensure_directories(self) -> None:
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)
        Path(self.ai_upload_dir).mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url.removeprefix("sqlite:///"))
            db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
