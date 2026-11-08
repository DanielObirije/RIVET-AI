import os
from dataclasses import dataclass
from typing import Final

DEFAULT_ALLOWED_ORIGINS = "http://localhost:3000"
DEFAULT_BROKER_URL: Final = "redis://localhost:6379/0"
# the worker computes the same default; DATABASE_URL overrides it
DEFAULT_DATABASE_URL: Final = "postgresql://rivet:rivet@localhost:5432/rivet"


@dataclass(frozen=True)
class Settings:
    allowed_origins: tuple[str, ...]


def load_settings() -> Settings:
    origins = os.getenv("CORS_ALLOWED_ORIGINS") or DEFAULT_ALLOWED_ORIGINS
    return Settings(
        allowed_origins=tuple(
            origin.strip() for origin in origins.split(",") if origin.strip()
        ),
    )


def broker_url() -> str:
    return (os.getenv("CELERY_BROKER_URL") or "").strip() or DEFAULT_BROKER_URL


def database_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip() or DEFAULT_DATABASE_URL
