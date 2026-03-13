from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    openai_api_key: str = ""

    # ── Logging ───────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: Optional[str] = None  # e.g. "logs/aegis.log"
    log_file_level: Optional[str] = None  # default same as log_level
    log_include_location: bool = False  # add module:func:line to each line

    # ── Database (Azure PostgreSQL) ────────────────────────────────────────
    db_host: str = "aidf-dev-postgres.postgres.database.azure.com"
    db_port: int = 5432
    db_name: str = "jobschedule"
    db_user: str = "jobschedule"
    db_password: str = "jobschedule@123"
    db_sslmode: str = "require"

    # ── SMTP / email ─────────────────────────────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # ── Onboarding score-and-evaluate scheduler (0 = disabled) ─────────────
    score_evaluate_interval_seconds: int = 0  # e.g. 300 for every 5 min; 0 = only manual/HTTP trigger

    class Config:
        env_file = str(ENV_FILE)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
