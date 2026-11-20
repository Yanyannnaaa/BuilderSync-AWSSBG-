from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    db_echo: bool = False

    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "ap-southeast-1"
    s3_bucket_name: str = ""
    s3_presign_seconds: int = 900

    email_provider: Literal["resend", "ses"] = "resend"
    email_from: str = "no-reply@example.org"
    email_batch_size: int = 50
    resend_api_key: str | None = None

    consecutive_absence_limit: int = 3
    warning_absence_threshold: int = 2
    max_upload_mb: int = 10

    secret_key: str = "change-me"
    session_hours: int = 8
    login_code_ttl_minutes: int = 10
    login_code_max_attempts: int = 5
    cookie_secure: bool = False
    demo_show_login_code: bool = False  # DEMO ONLY: returns the code to the login page
    dev_print_login_codes: bool = False  # NEVER enable in production

    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
