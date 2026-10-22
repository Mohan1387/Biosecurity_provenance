# Settings from environment variables
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repo root (backend/app/ -> backend/ -> repo root).
# Without this, os.getenv never sees keys defined only in .env.
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


class Settings:
    PROJECT_NAME: str = "TCP — Tiered Compute Platform"
    API_V1_PREFIX: str = "/api/v1"

    # JWT
    SECRET_KEY: str = os.getenv("JWT_SECRET", "change-me-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    )

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{Path(__file__).resolve().parent.parent / 'tcp.db'}",
    )

    # Anthropic
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    # Admin seed
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin")


settings = Settings()
