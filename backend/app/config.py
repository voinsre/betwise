import logging
import os
from pathlib import Path

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Find .env at project root (one level above backend/)
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    # Database
    DB_HOST: str = "db"
    DB_PORT: int = 5432
    DB_NAME: str = "betwise"
    DB_USER: str = "betwise"
    DB_PASSWORD: str = "changeme"
    DATABASE_URL: str = "postgresql+asyncpg://betwise:changeme@db:5432/betwise"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # API-Football v3
    API_FOOTBALL_KEY: str = ""
    API_FOOTBALL_BASE_URL: str = "https://v3.football.api-sports.io"

    # Google Gemini
    GEMINI_API_KEY: str = ""

    # OddsPapi
    ODDSPAPI_API_KEY: str = ""

    # Auth
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "changeme"
    JWT_SECRET: str = "changeme"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24

    # Model
    KELLY_MULTIPLIER: float = 0.25
    MIN_CONFIDENCE: int = 60
    MIN_EDGE: float = 0.05
    ODDS_MIN: float = 1.20
    ODDS_MAX: float = 2.20

    model_config = {"env_file": str(_ENV_FILE), "extra": "ignore"}


settings = Settings()

# Startup validation — warn on insecure defaults in production
_is_production = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("ENVIRONMENT") == "production")
if _is_production:
    _warnings = []
    if settings.JWT_SECRET == "changeme":
        _warnings.append("JWT_SECRET is still 'changeme' — set a strong random secret")
    if settings.ADMIN_PASSWORD == "changeme":
        _warnings.append("ADMIN_PASSWORD is still 'changeme' — set a strong password")
    if "changeme" in settings.DATABASE_URL:
        _warnings.append("DATABASE_URL still contains default password — set via Railway PostgreSQL plugin")
    if not settings.API_FOOTBALL_KEY:
        _warnings.append("API_FOOTBALL_KEY is empty — data sync will not work")
    for w in _warnings:
        logger.warning("CONFIG WARNING: %s", w)
