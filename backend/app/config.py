from pathlib import Path

from pydantic_settings import BaseSettings

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

    # Auth
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "changeme"
    JWT_SECRET: str = "changeme"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24

    # Model
    KELLY_MULTIPLIER: float = 0.25
    MIN_CONFIDENCE: int = 60
    MIN_EDGE: float = 0.02
    ODDS_MIN: float = 1.20
    ODDS_MAX: float = 2.50

    model_config = {"env_file": str(_ENV_FILE), "extra": "ignore"}


settings = Settings()
