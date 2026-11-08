import os
from dataclasses import dataclass
from typing import Final

DEFAULT_DEEPSEEK_API_URL: Final = "https://api.deepseek.com/chat/completions"
UPSTREAM_TIMEOUT_SECONDS: Final = 40.0
DEFAULT_BROKER_URL: Final = "redis://localhost:6379/0"
# the API computes the same default; DATABASE_URL overrides it
DEFAULT_DATABASE_URL: Final = "postgresql://rivet:rivet@localhost:5432/rivet"


@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str | None
    model: str


def load_deepseek_settings() -> DeepSeekSettings:
    api_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    return DeepSeekSettings(
        api_key=api_key or None,
        model=(os.getenv("DEEPSEEK_MODEL") or "").strip() or "deepseek-chat",
    )


def deepseek_api_url() -> str:
    return (os.getenv("DEEPSEEK_API_URL") or "").strip() or DEFAULT_DEEPSEEK_API_URL


def broker_url() -> str:
    return (os.getenv("CELERY_BROKER_URL") or "").strip() or DEFAULT_BROKER_URL


def database_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip() or DEFAULT_DATABASE_URL
